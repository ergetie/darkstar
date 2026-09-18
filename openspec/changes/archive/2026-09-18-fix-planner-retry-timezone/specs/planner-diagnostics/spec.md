## ADDED Requirements

### Requirement: Retry timestamps are timezone-aware UTC
All datetimes exchanged between `PlannerService` and `SchedulerService` SHALL be timezone-aware and expressed in UTC. `PlannerService` SHALL NOT produce naive datetimes for `next_retry_at` or `last_error_at`, and `SchedulerService` SHALL NOT attach a timezone to a datetime it receives from `PlannerService` — no `.replace(tzinfo=...)` coercion is permitted on the retry path.

Retry scheduling behavior SHALL be identical regardless of the host's UTC offset. A retry scheduled for "now plus N seconds" SHALL become due N seconds later in real time, whether the host runs at UTC+0, UTC+2, or any other offset.

#### Scenario: Immediate retry on a host at UTC+2
- **GIVEN** the host timezone is `Europe/Stockholm` during CEST (UTC+2)
- **WHEN** `clear_retry_suspension()` schedules an immediate retry
- **THEN** the planner MUST run on the next scheduler tick, within one tick interval
- **AND** the planner MUST NOT be delayed by the host's UTC offset

#### Scenario: Backoff duration on a non-UTC host
- **GIVEN** the host timezone is `Europe/Stockholm`
- **WHEN** a transient failure schedules a 60-second backoff
- **THEN** `next_retry_at` MUST be 60 seconds after the failure in real time, not 60 seconds plus the UTC offset

#### Scenario: Scheduler receives an aware timestamp
- **WHEN** `SchedulerService` reads `planner_service.next_retry_at` and it is not `None`
- **THEN** the value MUST already carry `tzinfo` set to UTC
- **AND** the scheduler MUST compare it directly against `datetime.now(UTC)` without modification

#### Scenario: retry_in_s agrees with the scheduler
- **GIVEN** a pending retry on a host at a non-zero UTC offset
- **WHEN** `retry_in_s` is read and the scheduler's due time is computed
- **THEN** the two MUST describe the same instant, within one second

### Requirement: Suspension is bounded and never silent
Automatic planning SHALL NOT remain suspended indefinitely. When retries are suspended by a config-blocking error, `PlannerService` SHALL still attempt a planning run after a bounded ceiling has elapsed since the suspension began, and SHALL continue attempting at no less than that ceiling thereafter until a run succeeds or the suspension is cleared.

While a suspension is active, the system SHALL surface a health issue so the stall is visible without reading logs.

#### Scenario: Suspension retries after the ceiling
- **GIVEN** the planner has been suspended by a config-blocking error and no `settings_saved` event has been received
- **WHEN** the suspension ceiling elapses
- **THEN** `PlannerService` MUST attempt one planning run
- **AND** if that run fails with a config-blocking code, the suspension MUST be re-applied with the ceiling restarting

#### Scenario: Active suspension is visible in health
- **GIVEN** retries are suspended
- **WHEN** `/api/health` is queried
- **THEN** the response MUST contain an issue with `category="planner"` reporting that automatic planning is suspended
- **AND** the issue MUST persist until the suspension clears

### Requirement: Skipped scheduler cycles are logged with a reason
When `SchedulerService` evaluates a planning cycle and declines to run the planner, it SHALL emit a log record naming the reason — suspension, a pending retry time, or a pending cadence time — and the time at which the next attempt becomes due. The scheduler SHALL NOT skip a planning cycle without a log record.

To avoid flooding a 30-second loop, repeated skips for the same unchanged reason MAY be logged at a reduced rate, provided that at least one record is emitted each time the reason changes and at least one record is emitted per suppressed interval.

#### Scenario: Skip due to pending retry is logged
- **GIVEN** `next_retry_at` is in the future
- **WHEN** the scheduler loop evaluates the planning branch
- **THEN** a log record MUST state that planning was skipped because a retry is pending, and give the due time

#### Scenario: Skip due to suspension is logged
- **GIVEN** `retry_suspended` is `True`
- **WHEN** the scheduler loop evaluates the planning branch
- **THEN** a log record MUST state that planning is suspended pending a configuration change

#### Scenario: Reason change is always logged
- **GIVEN** skips are being rate-limited for one reason
- **WHEN** the reason for skipping changes
- **THEN** a log record MUST be emitted for the new reason without waiting for the suppression interval

## MODIFIED Requirements

### Requirement: Retry policy keyed on error code
`PlannerService` SHALL track retry state including `last_error_code`, `last_error_at`, `next_retry_at`, `consecutive_failures`, and `retry_suspended`. All tracked datetimes SHALL be timezone-aware UTC. Retry cadence SHALL be determined by the last error code:

- **Config-blocking codes** (`CONFIG_INVALID`, `EV_MISSING_POWER`, `EV_INVALID_CAPACITY`): SHALL suspend automatic retries until the `settings_saved` event is received, subject to the bounded suspension ceiling.
- **Transient codes** (`PRICES_UNAVAILABLE`, `FORECAST_UNAVAILABLE`, `SOLVER_TIMEOUT`, `HA_UNAVAILABLE`): SHALL apply exponential backoff starting at 60s, doubling on each consecutive failure, capped at 300s. Reset to 60s on success.
- **Invariant/state codes** (`DATA_STALE`, `SOLVER_INFEASIBLE`, `SOLVER_UNDEFINED`, `NUMERIC_INVALID`, `INVALID_SCHEDULE`, `INITIAL_SOC_OUT_OF_RANGE`, `UNKNOWN`): SHALL retry at the normal cadence (typically 60s).
- **Warning-only codes** (`EV_DEADLINE_PAST`): SHALL NOT count as failures; planning SHALL proceed normally.

`INITIAL_SOC_OUT_OF_RANGE` SHALL NOT be config-blocking. A state-of-charge reading is sourced from live hardware, not from configuration, so a bad or missing reading SHALL retry on the normal cadence rather than waiting for a user to change settings.

A planning failure caused by Home Assistant being unreachable — connection refused, connection timeout, or a websocket transport failure — SHALL be classified as the transient code `HA_UNAVAILABLE` and SHALL recover without user action once Home Assistant returns.

On backend restart, `PlannerService` SHALL attempt one retry regardless of prior suspension state, then re-evaluate.

When the `settings_saved` event is received, `PlannerService` SHALL clear any active retry suspension and schedule a retry that becomes due on the next scheduler tick.

#### Scenario: Config error suspends retries
- **WHEN** the planner fails with code `EV_MISSING_POWER`
- **THEN** `retry_suspended` is `True`
- **AND** `next_retry_at` is `None`
- **AND** automatic retries do not run until `settings_saved` is received or the suspension ceiling elapses

#### Scenario: settings_saved clears suspension
- **GIVEN** `retry_suspended` is `True` after a config-blocking failure
- **WHEN** a `settings_saved` event is received
- **THEN** `retry_suspended` becomes `False`
- **AND** the next scheduled retry runs at the next scheduler tick

#### Scenario: Transient error backs off exponentially
- **WHEN** the planner fails three times in a row with code `PRICES_UNAVAILABLE`
- **THEN** the `next_retry_at` intervals from "now" are approximately 60s, then 120s, then 240s
- **AND** the interval never exceeds 300s

#### Scenario: Success resets backoff
- **GIVEN** a prior `PRICES_UNAVAILABLE` backoff had reached 240s
- **WHEN** the next run succeeds
- **THEN** `consecutive_failures` is 0
- **AND** subsequent transient failures restart backoff at 60s

#### Scenario: Restart attempts one retry
- **GIVEN** `retry_suspended` was `True` prior to backend shutdown
- **WHEN** the backend restarts
- **THEN** `PlannerService` performs one planning attempt
- **AND** if that attempt fails with a config-blocking code, suspension is re-applied

#### Scenario: Home Assistant outage recovers without user action
- **GIVEN** Home Assistant is unreachable and the planner fails to read battery state of charge
- **THEN** the failure MUST be classified `HA_UNAVAILABLE` and MUST NOT suspend retries
- **AND** when Home Assistant becomes reachable again, the next backoff retry MUST succeed with no configuration change

#### Scenario: Config save does not delay planning
- **GIVEN** the planner is running on its normal cadence with no active failure
- **WHEN** the user saves configuration
- **THEN** the next automatic planning run MUST occur no later than the normal cadence would have produced it
