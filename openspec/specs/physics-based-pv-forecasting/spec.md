## Purpose

Physics-first hybrid PV forecasting that uses the Open-Meteo solar forecast as the baseline, with bounded ML residuals learning local effects like shadows and efficiency differences.

## Requirements

### Requirement: Physics-Based PV Forecast as Base
The system SHALL use the **open-meteo solar forecast** (`OpenMeteoSolarForecast`, which returns plane-of-array / tilted irradiance with temperature derating) as the base PV forecast, with ML providing a bounded residual correction rather than direct predictions. The system SHALL NOT use a home-grown GHI->tilt transposition as the baseline.

#### Scenario: Baseline comes from open-meteo tilted irradiance
- **WHEN** generating a PV forecast for a time slot
- **THEN** the base PV value SHALL be the open-meteo solar forecast computed from `global_tilted_irradiance`, tilt/azimuth, and temperature
- **AND** the ML model SHALL add a bounded residual correction on top

#### Scenario: Home-grown transposition not used as baseline
- **WHEN** the open-meteo baseline is available
- **THEN** the system SHALL NOT substitute the home-grown POA/efficiency calculation as the baseline
- **AND** the base value SHALL reflect open-meteo's diffuse/direct split and temperature derating

#### Scenario: ML residual handles shadows
- **WHEN** actual PV is consistently lower than the open-meteo baseline at a specific time (indicating shading)
- **THEN** the ML residual model SHALL learn negative corrections for that hour
- **AND** future forecasts SHALL include the learned shadow correction within the configured bound

### Requirement: ML Learns Residuals
The ML training pipeline SHALL train PV models to predict the residual (actual - open-meteo baseline) rather than predicting PV directly, and the residual SHALL be applied as a bounded nudge.

#### Scenario: Training targets residual against open-meteo
- **WHEN** training data is prepared
- **THEN** the target variable SHALL be calculated as `pv_actual - openmeteo_baseline` for each historical slot
- **AND** the model SHALL learn to predict this residual value

#### Scenario: Inference applies bounded residual
- **WHEN** generating forecasts for future slots
- **THEN** the system SHALL take the open-meteo baseline first
- **AND** add the ML-predicted residual constrained so it cannot exceed the configured fraction of the baseline

#### Scenario: Efficiency auto-learned
- **WHEN** actual system efficiency differs from the open-meteo baseline assumptions
- **THEN** the ML residual SHALL learn the consistent difference within bounds
- **AND** no user configuration of efficiency SHALL be required

### Requirement: Training Data Filter
The ML training pipeline SHALL only train on slots with actual PV data and sun-up conditions.

#### Scenario: Sun-up filter
- **WHEN** preparing training data
- **THEN** the system SHALL filter slots where `pv_kwh IS NOT NULL`
- **AND** filter slots where `radiation > 10 OR pv_kwh > 0.01`
- **AND** skip nighttime slots where both radiation and production are zero

#### Scenario: Filter rationale
- **WHEN** a slot has radiation=0 and pv=0
- **THEN** the residual SHALL be 0 - 0 = 0
- **AND** this SHALL be excluded from training as it provides no learning signal

### Requirement: Retroactive Physics Calculation
For historical training data, the system SHALL use **stored open-meteo forecasts** as the residual reference, replacing retroactive home-grown physics calculation.

#### Scenario: Historical baseline from stored open-meteo forecasts
- **WHEN** training on historical data
- **THEN** the system SHALL use the stored open-meteo forecast for each slot as the baseline
- **AND** use `actual_pv - stored_openmeteo_baseline` as the training target

#### Scenario: Missing baseline handling
- **WHEN** a stored open-meteo baseline is unavailable for a historical slot
- **THEN** the system SHALL either backfill it from open-meteo historical data or skip that slot for PV training
- **AND** log the reason

### Requirement: Final Forecast Composition
The final PV forecast SHALL be the open-meteo baseline plus the bounded ML residual from the LightGBM PV model, clamped to a physical *generation* ceiling. The generation ceiling SHALL be derived from DC-side limits — panel capacity (`total_kwp * max_efficiency`) and the inverter DC input limit (`max_dc_input_kw`) — and SHALL NOT be reduced by the inverter AC output limit (`max_ac_power_kw`) on DC-coupled systems, because surplus PV above the AC limit charges the battery on the DC side and is still real generation. The effective ceiling (its value and which limit bound it) SHALL be logged when forecasts are generated. The previously removed Aurora corrector SHALL NOT add a separate residual.

#### Scenario: Final forecast calculation
- **WHEN** returning forecast via API
- **THEN** `final.pv_kwh` SHALL equal `openmeteo_baseline + bounded_lightgbm_residual`
- **AND** `final.pv_kwh` SHALL be capped at a DC-side physical generation ceiling (`min(total_kwp * max_efficiency, max_dc_input_kw) * slot_hours`)
- **AND** `base.pv_kwh` SHALL contain the open-meteo baseline value only

#### Scenario: DC-coupled system not clipped at AC limit
- **WHEN** the system topology is `dc_coupled` and the panel/DC capacity exceeds the inverter AC limit (e.g. 14.94 kWp panels, 10.3 kW DC, 10.3 kW AC)
- **THEN** the PV generation forecast SHALL be clipped only by the DC-side ceiling (panel capacity and DC input), never reduced to the AC output limit
- **AND** midday slots SHALL NOT be forced to a flat plateau at the AC limit

#### Scenario: Effective ceiling is observable
- **WHEN** a forecast run computes the physical generation ceiling
- **THEN** it SHALL log the ceiling value in kW and which input bound it (panel capacity vs DC input limit)
- **AND** a stale or misconfigured ceiling SHALL be diagnosable from the logs alone

#### Scenario: API transparency
- **WHEN** API consumers request forecast data
- **THEN** the response SHALL include `base.pv_kwh` (open-meteo) and the residual contribution
- **AND** consumers SHALL be able to see the component breakdown

#### Scenario: API backward compatibility
- **WHEN** API consumers request forecast data
- **THEN** the response structure SHALL remain compatible
- **AND** `final.pv_kwh` SHALL remain the authoritative forecast value

### Requirement: Open-Meteo Fallback
The system SHALL fall back to the **last successful stored open-meteo fetch** when a new fetch fails, and surface a warning, rather than computing a home-grown simplified forecast.

#### Scenario: Open-Meteo fetch fails
- **WHEN** an open-meteo fetch fails or throws an error
- **THEN** the system SHALL continue using the latest previously-stored open-meteo forecast for the planning window
- **AND** raise a warning via `record_forecast_error` so `SystemAlert` shows an "API unreachable - using last known forecast" banner

#### Scenario: Stored forecast exhausted
- **WHEN** an outage outlasts the stored forecast's coverage of the planning window
- **THEN** the system SHALL escalate the existing critical forecast-failure health issue
- **AND** SHALL NOT fabricate PV values from a home-grown formula

### Requirement: Multi-Array Support
The Open-Meteo baseline calculation SHALL support systems with multiple solar arrays at different orientations.

#### Scenario: Multiple arrays with different tilts
- **WHEN** config defines multiple arrays with different tilt/azimuth values
- **THEN** `OpenMeteoSolarForecast` SHALL calculate per-array estimates from Open-Meteo `global_tilted_irradiance`
- **AND** the open-meteo baseline SHALL be the sum of all array estimates
