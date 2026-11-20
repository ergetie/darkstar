# Capability: Database Retention

## Purpose

Keep the planner database at a bounded size by deleting history nobody reads any more and returning the space to the file system, without ever blocking the executor or recorder.

## Requirements

### Requirement: Short-lived tables are pruned
The system SHALL delete rows older than a window: `execution_log` after `executor.history_retention_days` (default 30, minimum 7), `planner_debug` after `learning.planner_debug_retention_days` (default 14, minimum 1), `s_index_history` after `learning.s_index_history_retention_days` (default 365, minimum 90).

#### Scenario: Old execution rows
- **WHEN** cleanup runs with `executor.history_retention_days` 30
- **THEN** `execution_log` rows with `executed_at` older than 30 days are deleted and newer rows remain

### Requirement: Learning data is kept forever by default
`slot_observations`, `slot_plans`, `slot_forecasts` (`learning.retention_days`), `price_forecasts` (`learning.price_forecast_retention_days`) and `learning_runs` (`learning.learning_runs_retention_days`) SHALL default to 0, meaning kept forever, and SHALL be pruned only when the user sets a positive value.

#### Scenario: Valuable data kept by default
- **WHEN** cleanup runs with default configuration on a database with three-year-old `slot_observations`, `price_forecasts` and `learning_runs` rows
- **THEN** none of those rows is deleted

#### Scenario: Opt-in limit
- **WHEN** `learning.retention_days` is 500
- **THEN** `slot_observations`, `slot_plans` and `slot_forecasts` rows older than 500 days are deleted and newer rows remain

### Requirement: Retention values are validated
A positive retention value below its minimum SHALL be raised to the minimum (400 days for `learning.retention_days` and `learning.price_forecast_retention_days`, 365 for `learning.learning_runs_retention_days`), and a non-numeric value SHALL fall back to the default, so a configuration mistake cannot delete training data.

#### Scenario: Value below minimum
- **WHEN** `learning.retention_days` is 30
- **THEN** 400 days are used

#### Scenario: Not a number
- **WHEN** `learning.price_forecast_retention_days` is "abc"
- **THEN** the default (keep forever) is used

#### Scenario: Zero not accepted for audit tables
- **WHEN** `executor.history_retention_days` is 0
- **THEN** the default of 30 days is used

### Requirement: Single retention implementation
The system SHALL perform all table pruning in the scheduled cleanup only: planner runs SHALL NOT delete `s_index_history` rows and training SHALL NOT delete `learning_runs` rows.

#### Scenario: Planner write
- **WHEN** a planner run stores an `s_index_history` row
- **THEN** no row is deleted by that write

### Requirement: Scheduled, non-blocking cleanup
Cleanup SHALL run in the background once the last successful run is 24 hours old or missing, first checked 10 minutes after start-up and then hourly. Deletes SHALL be done in batches of at most 5000 rows with a commit and a pause between batches, so a concurrent executor or recorder write waits only for one short batch. A failed or locked run SHALL NOT be recorded as successful and SHALL NOT affect the executor or the planner.

#### Scenario: Daily cadence
- **WHEN** the last successful cleanup was 25 hours ago
- **THEN** the next hourly check runs cleanup and stores the new completion time

#### Scenario: Locked database
- **WHEN** a batch fails with `database is locked`
- **THEN** the run ends without recording success and is retried at the next hourly check

### Requirement: One-time incremental auto-vacuum switch
At start-up, after a verified backup, the system SHALL apply retention cleanup, set `PRAGMA auto_vacuum=INCREMENTAL` and run a single full `VACUUM` before the application starts. It SHALL do nothing if auto-vacuum is already incremental.

#### Scenario: First start after upgrade
- **WHEN** a database with auto-vacuum off starts with enough free space and a backup
- **THEN** it is pruned, vacuumed once and afterwards reports auto-vacuum incremental

#### Scenario: Already switched
- **WHEN** auto-vacuum is already incremental
- **THEN** no backup, no prune and no `VACUUM` is performed

### Requirement: Safe skip of the switch
The switch SHALL be skipped with a warning, without failing start-up and without modifying the database, when no verified backup exists or free disk space on the database volume is below 1.2 times the post-cleanup data size plus 64 MB.

#### Scenario: Low disk space
- **WHEN** free space is below the required amount
- **THEN** the database is unchanged, a warning is logged and the application starts

#### Scenario: No backup
- **WHEN** the backup step produced no verified file
- **THEN** the switch is skipped and the application starts

### Requirement: Bounded incremental vacuum at runtime
After each cleanup the system SHALL return freed pages with `PRAGMA incremental_vacuum(1000)` repeated with a 100 ms pause until the freelist is empty or a 120 second budget is used, followed by a passive WAL checkpoint. It SHALL NOT run a full `VACUUM` at runtime.

#### Scenario: Freelist shrinks
- **WHEN** cleanup freed 5000 pages
- **THEN** `freelist_count` is lower after the run and the file size has shrunk accordingly

#### Scenario: No full vacuum
- **WHEN** the maintenance service runs
- **THEN** no `VACUUM` statement is executed on the database

#### Scenario: Time budget
- **WHEN** the freelist cannot be emptied within 120 seconds
- **THEN** the run stops and the remaining pages are returned by the next run
