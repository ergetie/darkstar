## ADDED Requirements

### Requirement: PV residual bound defaults to a symmetric 1.0 and honours zero
The PV hybrid forecast SHALL clamp the ML residual to +/-`forecasting.pv_residual_bound_fraction` times the Open-Meteo baseline. The default SHALL be 1.0 in both `config.default.yaml` and the code fallback. A configured value of 0 SHALL be honoured as "no ML nudge" and SHALL NOT be replaced by the default. The default SHALL apply only when the key is missing, None or not a finite non-negative number.

#### Scenario: Key missing
- **WHEN** `forecasting.pv_residual_bound_fraction` is absent from the config
- **THEN** the bound fraction used SHALL be 1.0

#### Scenario: Zero configured
- **WHEN** `forecasting.pv_residual_bound_fraction` is 0
- **THEN** the bound fraction used SHALL be 0.0
- **AND** the hybrid PV forecast SHALL equal the baseline (subject to existing clamps)

#### Scenario: Explicit value kept
- **WHEN** `forecasting.pv_residual_bound_fraction` is 0.5
- **THEN** the residual SHALL be clamped to +/-50% of the baseline per slot

#### Scenario: Invalid value
- **WHEN** the value is negative, NaN or non-numeric
- **THEN** the default 1.0 SHALL be used

### Requirement: Raw uncapped PV residual is persisted per slot
The forward forecast SHALL store the model's raw p50 PV residual (before bounding and personalization weighting) in `slot_forecasts.pv_ml_residual_raw_kwh`, so a different bound can be evaluated exactly later. The column SHALL be nullable; rows stored before it existed and baseline-only forecasts SHALL read as NULL. Storing it SHALL NOT change the forecast values used for planning. It is added by a nullable-column database migration.

#### Scenario: Hybrid mode stores raw residual
- **WHEN** a forward forecast is generated in hybrid mode and the raw p50 residual is +0.4 kWh while the bound allows only +0.1 kWh
- **THEN** `pv_ml_residual_raw_kwh` SHALL be 0.4
- **AND** `pv_forecast_kwh` SHALL reflect the bounded residual

#### Scenario: Baseline-only mode
- **WHEN** no PV models are available or Aurora PV is disabled
- **THEN** `pv_ml_residual_raw_kwh` SHALL be NULL

#### Scenario: Upgrade of existing database
- **WHEN** the Alembic migration runs on a database with existing `slot_forecasts` rows
- **THEN** the column SHALL be added as nullable with existing rows NULL and no rows lost
- **AND** downgrade SHALL remove the column

### Requirement: Panel orientation honours zero
The physics PV estimate SHALL use a configured solar array `tilt` and `azimuth` of 0 as given (tilt 0 is a flat array, azimuth 0 is north). Defaults (tilt 30, azimuth 180) SHALL apply only when the key is missing or None.

#### Scenario: Flat array
- **WHEN** an array has `tilt: 0`
- **THEN** the estimate SHALL use a tilt of 0, not 30

#### Scenario: North-facing array
- **WHEN** an array has `azimuth: 0`
- **THEN** the estimate SHALL use azimuth 0 (HA convention), not 180

#### Scenario: Missing orientation
- **WHEN** `tilt` or `azimuth` is missing or None
- **THEN** 30 and 180 SHALL be used respectively
