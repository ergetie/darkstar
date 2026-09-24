## ADDED Requirements

### Requirement: No corrector surfaces in API or UI
The system SHALL NOT expose corrector status or correction history in any API response or UI component. Leftover `*_error.lgb` files in the models directory SHALL NOT affect the Model Training display.

#### Scenario: Leftover corrector files present
- **WHEN** `load_error.lgb` or `pv_error.lgb` exist in the models directory
- **THEN** the Model Training card shows no Corrector tile
- **AND** the Main Models age is computed only from `*model*` files

#### Scenario: Forecast API response
- **WHEN** a client requests the Aurora forecast dashboard data
- **THEN** the response contains no `correction_history` field

### Requirement: Corrector columns are removed from the database on upgrade
The database migration SHALL drop `pv_correction_kwh`, `load_correction_kwh` and `correction_source` from `slot_forecasts` without losing any other data, and SHALL be idempotent and reversible.

#### Scenario: Existing install upgrades
- **WHEN** `alembic upgrade head` runs on a DB that has the correction columns
- **THEN** the columns are removed
- **AND** every `slot_forecasts` row and all other column values, indexes and unique constraints are preserved

#### Scenario: Columns already absent
- **WHEN** the migration runs on a DB without those columns
- **THEN** it completes without error and makes no changes

#### Scenario: Downgrade
- **WHEN** `alembic downgrade -1` runs after the upgrade
- **THEN** the three columns are re-added with defaults `0`, `0` and `'none'`
