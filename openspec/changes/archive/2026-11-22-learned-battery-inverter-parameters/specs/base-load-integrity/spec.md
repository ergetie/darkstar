## ADDED Requirements

### Requirement: Legacy bare source markers are read as legacy rows
The historical base-load migration SHALL read a `quality_flags` value that is exactly `mariadb_sync` or `auto_recorded` as the object `{"source": <name>}`, a legacy row without `recording`, and SHALL rewrite it only when a rule flags it, keeping `source`. Any other non-object value SHALL still be skipped, counted as unparseable and named in one warning listing at most five slot timestamps.

#### Scenario: Legacy marker with a clamped counter
- **GIVEN** a row with `quality_flags` `mariadb_sync`, `load_kwh` 0 and `water_kwh` 0.75
- **WHEN** the migration runs
- **THEN** the row is flagged `legacy_counter_clamp`, its `source` is `mariadb_sync` and it is not counted as unparseable

#### Scenario: Legacy marker without a problem
- **GIVEN** a row with `quality_flags` `auto_recorded` that no rule flags
- **WHEN** the migration runs
- **THEN** the stored value is unchanged

#### Scenario: Other text is still skipped
- **GIVEN** a row with `quality_flags` `{not json` or `[1]`
- **WHEN** the migration runs
- **THEN** the row is left untouched, counted as unparseable and named in the single summary warning
