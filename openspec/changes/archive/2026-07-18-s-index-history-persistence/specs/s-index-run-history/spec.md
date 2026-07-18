# S-Index Run History

## ADDED Requirements

### Requirement: Per-run S-Index record persistence
The system SHALL persist one row to an `s_index_history` database table for every successful planner run that produces a schedule. Each row SHALL contain an autoincrement primary key, a `created_at` timestamp stored as an ISO-8601 UTC string, and a `payload` TEXT column holding the JSON-serialized S-Index debug record — the same dictionary exposed as `meta.s_index` in the schedule output.

Persistence SHALL be active on all installs without any configuration toggle, and SHALL NOT be gated on the learning subsystem's `enable` flag.

#### Scenario: Successful run writes one row
- **WHEN** a planner run completes and produces a schedule with a non-empty S-Index debug record
- **THEN** exactly one new row is inserted into `s_index_history`
- **AND** the row's `payload` deserializes to the same dictionary written to the schedule output's `meta.s_index`
- **AND** the row's `created_at` is an ISO-8601 UTC timestamp

#### Scenario: Persistence is independent of learning enable flag
- **WHEN** a planner run completes with the learning subsystem's `enable` flag set to false
- **THEN** the `s_index_history` row is still written

### Requirement: Persistence failure never fails the planner run
A failure to write the `s_index_history` row (database unavailable, lock contention, serialization error) SHALL be logged as a warning and SHALL NOT raise out of the planner run. The schedule output SHALL be unaffected.

#### Scenario: Database write fails
- **WHEN** the `s_index_history` insert raises an exception during a planner run
- **THEN** a warning is logged
- **AND** the planner run completes successfully and the schedule output is produced unchanged

#### Scenario: Store unavailable
- **WHEN** the learning engine or its store is not initialized (e.g., running outside full application context)
- **THEN** the write is skipped without raising

### Requirement: Bounded retention
The write path SHALL delete rows from `s_index_history` whose `created_at` is older than 365 days, computed in UTC, so the table remains bounded (~19 MB at the observed 46 runs/day). The `created_at` column SHALL be indexed to keep the range delete cheap.

#### Scenario: Old rows are pruned on write
- **GIVEN** `s_index_history` contains rows with `created_at` older than 365 days
- **WHEN** a new row is written after a planner run
- **THEN** all rows older than 365 days are deleted in the same write path
- **AND** rows within the 365-day window are retained

#### Scenario: Retention comparison is UTC-safe
- **WHEN** the retention cutoff is computed
- **THEN** it is derived from the current UTC time and compared against the stored ISO-8601 UTC `created_at` values
