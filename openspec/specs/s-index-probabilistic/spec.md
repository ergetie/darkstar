# S-Index Probabilistic

## Purpose

Supply the S-Index with probabilistic PV and load forecast bounds (P10/P90) from the Aurora ML database, so the safety floor can account for forecast uncertainty.

## Requirements

### Requirement: Probabilistic data retrieval from Aurora database
The system SHALL correctly retrieve and return probabilistic forecast bounds (P10/P90) from the Aurora ML database to support S-Index probabilistic calculations.

#### Scenario: Successfully retrieve daily probabilistic aggregates
- **WHEN** the planner requests forecast data via `_get_forecast_data_aurora()`
- **THEN** the function SHALL return daily aggregates for PV and Load P10/P90 bounds
- **AND** the data SHALL be accessible via the `daily_probabilistic` key in the return value

#### Scenario: Correctly access nested probabilistic fields
- **GIVEN** `get_forecast_slots()` returns records with nested structure `{"probabilistic": {"pv_p10": X, ...}}`
- **WHEN** `_get_forecast_data_aurora()` processes extended records
- **THEN** it SHALL access P10/P90 values via `rec.get("probabilistic", {}).get("pv_p10")` pattern
- **AND** apply PV and Load corrections to the probabilistic bounds

#### Scenario: Aggregate probabilistic data by date
- **GIVEN** extended forecast records with probabilistic bounds and correction values
- **WHEN** the function aggregates daily totals
- **THEN** it SHALL sum `pv_p10 + pv_correction` for each date
- **AND** it SHALL sum `load_p10 + load_correction` for each date
- **AND** it SHALL produce four dictionaries: `daily_pv_p10`, `daily_pv_p90`, `daily_load_p10`, `daily_load_p90`

#### Scenario: Return complete forecast result structure
- **WHEN** `_get_forecast_data_aurora()` completes successfully
- **THEN** the return value SHALL contain:
  - `slots`: list of slot-level forecasts
  - `daily_pv_forecast`: dict of daily PV totals
  - `daily_load_forecast`: dict of daily Load totals
  - `daily_probabilistic`: dict with keys `pv_p10`, `pv_p90`, `load_p10`, `load_p90`
