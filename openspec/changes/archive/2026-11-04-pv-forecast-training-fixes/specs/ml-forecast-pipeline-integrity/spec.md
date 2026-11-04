## ADDED Requirements

### Requirement: Stored raw ML residual survives planner re-upserts
The stored per-slot raw p50 ML residual SHALL NOT be overwritten with a missing value when forecasts are written again without that field. A non-missing incoming value SHALL replace the stored one.

#### Scenario: Planner re-upserts slots without the residual
- **WHEN** a forecast row with a stored residual is upserted with the residual absent
- **THEN** the stored residual SHALL be unchanged

#### Scenario: New residual supplied
- **WHEN** the upsert carries a residual value
- **THEN** the stored value SHALL be updated

### Requirement: Baseline backfill honours zero tilt and zero azimuth
The Open-Meteo PV baseline backfill SHALL use the configured tilt and azimuth of each array, treating 0 as a valid value; only a missing value SHALL use the default (tilt 30, azimuth 180), matching the live forecast path.

#### Scenario: Flat array
- **WHEN** an array has tilt 0
- **THEN** the backfill SHALL use tilt 0

#### Scenario: North-facing array
- **WHEN** an array has azimuth 0
- **THEN** the backfill SHALL treat it as azimuth 0 (north) and NOT as 180 (south)

#### Scenario: Missing values
- **WHEN** tilt or azimuth is absent or null
- **THEN** defaults 30 and 180 SHALL be used
