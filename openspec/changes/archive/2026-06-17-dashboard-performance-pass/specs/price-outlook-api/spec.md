## ADDED Requirements

### Requirement: Daily outlook query is bounded to the latest forecast run
The daily price outlook query SHALL read only the rows belonging to the most recent forecast run, identified by the maximum `issue_timestamp` in `price_forecasts`, rather than scanning the entire forecast history. The endpoint's response fields, level/confidence classifications, and statuses SHALL remain unchanged.

#### Scenario: Only the latest run is read
- **WHEN** the outlook query executes against a `price_forecasts` table containing many historical forecast runs
- **THEN** only rows with the maximum `issue_timestamp` and `days_ahead` between 1 and 7 are read
- **AND** no per-row processing is performed on rows from older runs

#### Scenario: Output is unchanged from full-history processing
- **WHEN** the latest forecast run contains a complete D+1 through D+7 set
- **THEN** the returned `days` array, `reference_avg`, classifications, and `status` are identical to the previously specified outlook behavior

#### Scenario: Latest run empty or missing
- **WHEN** no forecast rows exist or the latest run yields no usable days
- **THEN** the endpoint returns the existing `no_data` response (`enabled: true`, empty `days`, `status: "no_data"`)
