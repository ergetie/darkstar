## ADDED Requirements

### Requirement: Runtime monitor status is visible in the UI

The UI SHALL provide a read-only panel that displays the runtime invariant monitor status from `GET /api/system/monitors`, including each invariant's latest result, any active violation episodes, and overall monitor health. The panel SHALL degrade gracefully when the endpoint is unavailable (show an error/loading state, not crash the page).

#### Scenario: Monitors are healthy

- **WHEN** the operator opens the monitor status panel and all invariants pass
- **THEN** the panel lists each invariant with a healthy status and shows no active violations

#### Scenario: An invariant is violated

- **WHEN** one or more invariants have an active violation episode
- **THEN** the panel highlights the violated invariant(s) with their details (first-detected time and message)

#### Scenario: Endpoint unavailable

- **WHEN** `GET /api/system/monitors` fails or is unreachable
- **THEN** the panel shows an error/empty state without breaking the surrounding page

### Requirement: The obsolete data_quality_daily table is removed

The `data_quality_daily` table and its `DataQualityDaily` model SHALL be removed via a database migration. The runtime invariant monitors are the live-era replacement for daily data-quality evaluation.

#### Scenario: Migration applied

- **WHEN** the migration runs on an existing database
- **THEN** the `data_quality_daily` table is dropped and the application starts without referencing it

#### Scenario: No live code references remain

- **WHEN** the codebase is searched for `data_quality_daily` / `DataQualityDaily` after the change
- **THEN** no model definition, writer, reader, or API references it
