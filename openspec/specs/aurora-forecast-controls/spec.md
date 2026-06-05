## Purpose

Provide explicit, domain-specific Aurora forecast controls for load and PV forecasting.

## Requirements

### Requirement: Aurora forecast controls are domain-specific
The Aurora Command Center SHALL expose independent controls for Aurora load forecasting and Aurora PV forecasting so users can disable one forecast domain without disabling the other.

#### Scenario: Both Aurora forecast domains enabled
- **WHEN** `forecasting.aurora_load_enabled` is true
- **AND** `forecasting.aurora_pv_enabled` is true
- **THEN** load forecasting SHALL use Aurora ML output
- **AND** PV forecasting SHALL use the Open-Meteo baseline plus bounded Aurora PV tuning when the ramp permits it

#### Scenario: Load forecasting disabled only
- **WHEN** `forecasting.aurora_load_enabled` is false
- **AND** `forecasting.aurora_pv_enabled` is true
- **THEN** load forecasting SHALL use the existing HA load profile fallback
- **AND** PV forecasting SHALL continue to use the Open-Meteo baseline plus bounded Aurora PV tuning when the ramp permits it

#### Scenario: PV forecasting disabled only
- **WHEN** `forecasting.aurora_load_enabled` is true
- **AND** `forecasting.aurora_pv_enabled` is false
- **THEN** load forecasting SHALL use Aurora ML output
- **AND** PV forecasting SHALL use the Open-Meteo baseline only
- **AND** no Aurora PV residual or personal tuning SHALL be applied

#### Scenario: Both Aurora forecast domains disabled
- **WHEN** `forecasting.aurora_load_enabled` is false
- **AND** `forecasting.aurora_pv_enabled` is false
- **THEN** load forecasting SHALL use the existing HA load profile fallback
- **AND** PV forecasting SHALL use the Open-Meteo baseline only

### Requirement: PV baseline remains available when Aurora PV forecasting is disabled
Disabling Aurora PV forecasting SHALL disable only the PV ML residual/personal tuning. The system SHALL continue to fetch, store, expose, and use the Open-Meteo PV baseline.

#### Scenario: PV disabled still stores Open-Meteo baseline
- **WHEN** Aurora PV forecasting is disabled
- **AND** a successful Open-Meteo fetch occurs
- **THEN** the system SHALL store `openmeteo_pv_forecast_kwh` per slot
- **AND** `base.pv_kwh` SHALL contain the Open-Meteo baseline
- **AND** `final.pv_kwh` SHALL equal the Open-Meteo baseline clamped to the physical ceiling

### Requirement: Forecast-version selector is not user-facing
The UI SHALL NOT expose the legacy `active_forecast_version` selector as the control for Aurora forecasting because it changes multiple forecast domains at once and the `baseline_7_day_avg` name no longer describes PV behavior.

#### Scenario: Aurora Controls card shows explicit toggles
- **WHEN** the user views the Aurora Controls card
- **THEN** the UI SHALL show an "Aurora load forecasting" toggle
- **AND** the UI SHALL show an "Aurora PV forecasting" toggle
- **AND** the UI SHALL NOT ask the user to choose `aurora` vs `baseline_7_day_avg`

#### Scenario: Archived Forecasting page removed
- **WHEN** the frontend routes and source files are reviewed
- **THEN** `frontend/src/pages/archive/Forecasting.tsx` SHALL be removed
- **AND** no user-facing route SHALL expose the old forecast-version selector
