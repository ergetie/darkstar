# Spec: Executor Health Check

## Purpose
Make the executor health check in the health banner work against the real executor status instead of silently doing nothing.

## Requirements

### Requirement: Executor not running is reported
The health check SHALL report a critical issue with code `EXECUTOR_NOT_RUNNING` when the executor is enabled in config, not paused, and its loop thread is not alive. It SHALL read the status of the existing executor instance and SHALL NOT create or initialise an executor.

#### Scenario: Enabled but thread dead
- **WHEN** the executor is enabled, not paused, and its thread is not alive
- **THEN** the health issues contain a critical `EXECUTOR_NOT_RUNNING` issue

#### Scenario: Paused executor is healthy
- **WHEN** the executor is paused and its thread is alive and sleeping
- **THEN** no executor issue is reported

#### Scenario: Disabled executor is healthy
- **WHEN** the executor is disabled in config
- **THEN** no executor issue is reported

### Requirement: Failed last run is reported
The health check SHALL report a warning issue with code `EXECUTOR_LAST_RUN_FAILED` containing the last error text when the executor's last run status is `error`.

#### Scenario: Last run failed
- **WHEN** the executor status shows `last_run_status` `error` with an error message
- **THEN** the health issues contain a warning including that message

### Requirement: Regression protection and failure visibility
The health check and the `/api/executor/health` route SHALL share one status computation. A failure inside the check SHALL NOT raise and SHALL be logged at warning level, not debug. The test suite SHALL fail if the health check cannot obtain the executor status because of a missing or renamed function or attribute.

#### Scenario: Broken import is caught by tests
- **WHEN** the function that provides the executor status is renamed or removed
- **THEN** the executor health test fails

#### Scenario: Check failure does not break health
- **WHEN** reading the executor status raises
- **THEN** the health response is still returned and a warning is logged

#### Scenario: No executor instance while disabled
- **WHEN** no executor instance exists and the executor is disabled in config
- **THEN** no executor issue is reported and no instance is created

### Requirement: Uninitialised executor is reported
The health check SHALL report a critical issue with code `EXECUTOR_NOT_INITIALIZED` when the executor is enabled in config but no executor instance exists. It SHALL NOT create an executor instance.

#### Scenario: Enabled but no instance
- **WHEN** the executor is enabled in config and no executor instance exists
- **THEN** the health issues contain a critical `EXECUTOR_NOT_INITIALIZED` issue and no instance is created

### Requirement: Stalled executor loop is reported
The health check SHALL report a warning issue with code `EXECUTOR_STALE` when the loop thread is alive, the executor is enabled and not paused, and the last tick started more than `max(3 x interval_seconds, 600 s)` ago. No tick yet SHALL NOT be reported as stale.

#### Scenario: Last tick too old
- **WHEN** the thread is alive, enabled, not paused, and `last_run_at` is older than the threshold
- **THEN** the health issues contain a warning `EXECUTOR_STALE`

#### Scenario: Recent tick
- **WHEN** `last_run_at` is within the threshold
- **THEN** no stale issue is reported

#### Scenario: Paused or disabled is never stale
- **WHEN** the executor is paused or disabled and `last_run_at` is old
- **THEN** no stale issue is reported

### Requirement: Config save starts an enabled executor
Saving the configuration with `executor.enabled` true SHALL start the executor loop thread of the existing instance when it is not running. It SHALL NOT create an instance. Saving with `executor.enabled` false SHALL leave the loop idle without ticks or writes.

#### Scenario: Enable through config save
- **WHEN** a config save sets `executor.enabled` true and the executor thread is not alive
- **THEN** the executor is started

#### Scenario: Already running
- **WHEN** a config save keeps `executor.enabled` true and the thread is alive
- **THEN** no second thread is started

#### Scenario: Disable through config save
- **WHEN** a config save sets `executor.enabled` false
- **THEN** the loop idles without ticking and the executor is not started

#### Scenario: No instance
- **WHEN** a config save runs and no executor instance exists
- **THEN** no instance is created and the save succeeds
