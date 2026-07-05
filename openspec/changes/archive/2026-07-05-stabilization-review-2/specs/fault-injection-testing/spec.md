## ADDED Requirements

### Requirement: Home Assistant unavailability scenarios
The test suite SHALL include scenarios where Home Assistant is unreachable (connection refused, timeouts, HTTP 404/5xx on entities) during executor ticks and recorder cycles, asserting that the system degrades safely: no unhandled exception escapes the loop, no partial/inconsistent command sequence is sent, failures are logged and recorded (`execution_log.success = false`), and normal operation resumes when connectivity returns.

#### Scenario: HA offline during executor tick
- **WHEN** every HA call fails with a connection error for the duration of a tick
- **THEN** the tick completes without crash, no command is considered applied, the failure is recorded, and the next tick retries normally

#### Scenario: HA returns 404 for a required entity
- **WHEN** a state read returns HTTP 404 (entity missing, e.g. during HA restart)
- **THEN** the executor treats the tick as failed-safe (no fallback to stale or assumed values that would trigger commands) and logs the specific entity

### Requirement: Price data degradation scenarios
The test suite SHALL include scenarios with missing tomorrow-prices, partially missing slots, and a completely unavailable price source, asserting the planner either produces a safe schedule from available data or declines to overwrite the last good schedule — and never plans against fabricated prices.

#### Scenario: Nordpool fetch fails entirely
- **WHEN** the price source raises on fetch during a planner run
- **THEN** the previously generated schedule remains in effect and the failure is surfaced, rather than an empty or zero-price schedule being written

### Requirement: Sensor anomaly scenarios
The test suite SHALL include scenarios with implausible sensor inputs — spikes, negative cumulative-meter deltas, stuck values, and unit-scale outliers — asserting that recorder observations and forecast inputs are guarded (flagged, clamped, or rejected per existing quality rules) and that one bad reading cannot produce a wildly wrong recorded slot or plan input.

#### Scenario: Cumulative meter goes backwards
- **WHEN** a cumulative energy sensor reports a value lower than the previous reading
- **THEN** the recorder does not record a negative energy delta and the slot is flagged per the data-quality rules

### Requirement: Restart and staleness scenarios
The test suite SHALL include scenarios covering application restart mid-slot and an executor running against a schedule older than the planner cadence, asserting recorder state resumes without double-counting or gaps, and the executor's stale-schedule safeguard holds rather than acting on outdated plans.

#### Scenario: Restart mid-slot
- **WHEN** the application restarts halfway through a 15-minute slot with recorder state persisted
- **THEN** the eventual slot observation contains no double-counted and no lost energy beyond documented tolerance

#### Scenario: Schedule far past freshness
- **WHEN** the newest schedule is older than the configured freshness bound
- **THEN** the executor holds (safe default behavior) instead of executing the stale plan, and the condition is logged

### Requirement: DST transition scenarios
The test suite SHALL include planner, recorder, and executor scenarios across both DST transitions (23-hour and 25-hour days, Europe/Stockholm), asserting slot sequences remain continuous and non-overlapping and no component crashes or mislabels slots.

#### Scenario: Spring-forward planning day
- **WHEN** a schedule is generated for the 23-hour spring DST day
- **THEN** the slot sequence is continuous with no phantom or duplicated slots and downstream consumers accept it

### Requirement: Fault-injection tests gate CI
Fault-injection scenarios SHALL run as part of the standard pytest suite (hermetic, no network, no live system) so they gate every merge like existing tests.

#### Scenario: Suite runs hermetically
- **WHEN** the full test suite runs in CI with no network access
- **THEN** all fault-injection tests execute against mocks/fixtures and pass or fail deterministically
