# Spec: Planner Run Archive

## Purpose
Keep a compressed record of every planner run for a configurable period so past decisions can be replayed and shared for support, and let the user download or clear it from the Debug page.

## Requirements

### Requirement: Every planner run is archived
The system SHALL write one compressed archive record for each run executed by the planner service, whether the run succeeds or fails, when `debug.plan_archive_enabled` is true. Each record SHALL contain the run's inputs, the plan as written to `schedule.json`, the initial SoC, the safety floor, the config version, the redacted effective config, the solver status, the planner version, and the start and finish time.

#### Scenario: Successful run
- **WHEN** the planner service completes a run successfully
- **THEN** one `.json.gz` record exists for that run containing inputs, plan, initial SoC, safety floor, config version, solver status and outcome `ok`

#### Scenario: Failed run
- **WHEN** the planner service run fails with a planner error
- **THEN** a record with outcome `error` exists containing the error code, message and details, and any inputs gathered before the failure

#### Scenario: Run that fails before inputs exist
- **WHEN** fetching inputs raises an error
- **THEN** a record with outcome `error` and the error is still written, with empty inputs

#### Scenario: Archive disabled
- **WHEN** `debug.plan_archive_enabled` is false
- **THEN** no record is written and no archive directory is created

#### Scenario: Replay fidelity
- **WHEN** a record's plan and config are fed to the offline Kepler solver
- **THEN** the record holds every input the solver needs (per-slot prices, adjusted PV and load, initial SoC, safety floor, config)

### Requirement: Executor errors are recorded with the run
Each record SHALL include the failed executor actions logged since the previous archived run, newest last, capped at 50 entries.

#### Scenario: Executor failure between runs
- **WHEN** the executor logs a failed action after run A and before run B
- **THEN** record B lists that failure with its time, slot and message and record A does not

#### Scenario: Cap
- **WHEN** more than 50 failures occurred since the previous run
- **THEN** record contains the 50 most recent and an `executor_errors_truncated` count

### Requirement: Archiving never disturbs planning
Archive failures SHALL be logged as warnings and SHALL NOT change the planner's result, retry policy, `schedule.json` or the API responses.

#### Scenario: Archive directory not writable
- **WHEN** the archive directory cannot be written
- **THEN** the planner run still succeeds and a warning is logged

#### Scenario: Atomic files
- **WHEN** a record is written
- **THEN** it appears under its final name only when complete, and an interrupted write leaves no partial `.json.gz` file

### Requirement: Archive content is redacted
Records SHALL NOT contain config values whose key names denote secrets, and their text SHALL be passed through the diagnostics redaction before it is compressed.

#### Scenario: Secret in config
- **WHEN** the effective config contains a token or password key
- **THEN** the record's config omits its value

#### Scenario: Host in an error message
- **WHEN** a planner error message contains a public host or IP
- **THEN** the stored message contains the redaction placeholder instead

### Requirement: Retention is configurable
Records older than `debug.plan_archive_retention_days` (default 60, minimum 7) SHALL be deleted after each archive write. A value below the minimum is raised to the minimum; a missing, non-numeric, zero or negative value falls back to 60.

#### Scenario: Old records pruned
- **WHEN** a record is written with retention 60 and a file is 61 days old
- **THEN** the old file is deleted and newer files remain

#### Scenario: Invalid value
- **WHEN** retention is "abc", 0 or 3
- **THEN** 60, 60 and 7 days are used respectively

#### Scenario: Unrelated files untouched
- **WHEN** pruning runs
- **THEN** only files matching the archive naming pattern are removed

### Requirement: Archive download
The system SHALL provide a zip download of the archive, optionally limited to the last N days, containing the record files unchanged and a `manifest.json` listing each file with its time, outcome and size.

#### Scenario: Download all
- **WHEN** a user requests the download with no limit
- **THEN** the zip contains every record and a manifest

#### Scenario: Download limited
- **WHEN** a user requests the last 1 day
- **THEN** the zip contains only records from the last 24 hours

#### Scenario: Empty archive
- **WHEN** the archive holds no records
- **THEN** the request fails with HTTP 404 and a clear message

#### Scenario: Temporary file removed
- **WHEN** the download finishes or fails
- **THEN** no temporary zip remains on disk

#### Scenario: Concurrent download
- **WHEN** a download is already running
- **THEN** a second request fails with HTTP 409

### Requirement: Archive summary and clear
The system SHALL report the archive's enabled state, retention days, record count, total bytes, and oldest and newest record time, and SHALL delete all records on request.

#### Scenario: Summary
- **WHEN** the summary is requested
- **THEN** it returns enabled, retention_days, count, total_bytes, oldest and newest without decompressing records

#### Scenario: Clear
- **WHEN** a user clears the archive
- **THEN** all record files are deleted, other files in `data/` are untouched, and the summary shows zero records

### Requirement: Debug page archive card
The Debug page SHALL show an archive card with the summary, a download control with range choice (all, last 7 days, last 24 hours) and a clear button that requires confirmation, following the design system, with progress and error feedback.

#### Scenario: Download in progress
- **WHEN** a download is running
- **THEN** the download control shows a busy state and is disabled until it finishes or fails

#### Scenario: Download fails
- **WHEN** the download fails
- **THEN** an error toast with the reason is shown

#### Scenario: Clear confirmed
- **WHEN** the user confirms the clear
- **THEN** the archive is emptied and the card shows zero records

#### Scenario: Clear cancelled
- **WHEN** the user cancels the confirmation
- **THEN** nothing is deleted

#### Scenario: Empty or disabled
- **WHEN** the archive is empty
- **THEN** the download button is disabled; if archiving is disabled the card says so
