## MODIFIED Requirements

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
