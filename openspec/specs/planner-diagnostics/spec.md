# Spec: Planner Diagnostics

## Purpose

TBD - Structured error handling, diagnostics, and retry policies for the planner.

## Requirements

### Requirement: Typed planner error codes
The planner SHALL expose a typed `PlannerErrorCode` enumeration covering all known failure modes. Every planner failure emitted to any caller (service layer, logs, WebSocket, HealthIssue) SHALL carry one of these codes.

The enumeration SHALL include at minimum: `CONFIG_INVALID`, `INITIAL_SOC_OUT_OF_RANGE`, `DATA_STALE`, `EV_MISSING_POWER`, `EV_INVALID_CAPACITY`, `EV_DEADLINE_PAST`, `PRICES_UNAVAILABLE`, `FORECAST_UNAVAILABLE`, `NUMERIC_INVALID`, `SOLVER_INFEASIBLE`, `SOLVER_TIMEOUT`, `SOLVER_UNDEFINED`, `INVALID_SCHEDULE`, `HA_UNAVAILABLE`, `UNKNOWN`.

Each code SHALL have an associated user-facing message (short, suitable for a banner headline) and fix-hint list (actionable, suitable for a details drawer).

#### Scenario: Every failure carries a code
- **WHEN** the planner fails for any reason
- **THEN** the emitted failure record includes a `code` field set to a value from the `PlannerErrorCode` enumeration
- **AND** the code is never `None` or empty for a failure

#### Scenario: Unknown exceptions fall back to UNKNOWN
- **WHEN** the planner raises an unexpected exception not covered by a specific code
- **THEN** the failure record's code is `UNKNOWN`
- **AND** the human message contains the exception type and truncated exception text

#### Scenario: Code carries user message and fix hints
- **WHEN** a failure record with code `INITIAL_SOC_OUT_OF_RANGE` is produced
- **THEN** a call to `code.user_message()` returns a non-empty string suitable for display
- **AND** a call to `code.fix_hints()` returns a non-empty list of strings

### Requirement: HealthIssue carries structured diagnostic data
The `HealthIssue` record SHALL support three optional fields in addition to its existing `category`, `severity`, `message`, `guidance`, and `entity_id` fields: `code` (string, machine-readable error code), `details` (dict, structured diagnostic payload), and `retry_in_s` (integer, seconds until next automatic retry attempt).

When serialized via `to_dict()`, these fields SHALL be included when non-None and omitted when None.

The `/api/health` response body `issues[]` entries SHALL reflect this serialization behavior.

#### Scenario: Backwards compatible serialization
- **WHEN** a `HealthIssue` has no `code`, `details`, or `retry_in_s`
- **THEN** the serialized dict does not contain those keys
- **AND** existing consumers reading only the original five fields continue to work

#### Scenario: Populated structured fields serialize
- **WHEN** a `HealthIssue` has `code="EV_MISSING_POWER"`, `details={"charger_id": "ev1"}`, and `retry_in_s=120`
- **THEN** the serialized dict includes `"code": "EV_MISSING_POWER"`, `"details": {"charger_id": "ev1"}`, and `"retry_in_s": 120`

### Requirement: Planner health check surfaces last failure
The `HealthChecker` SHALL include a `check_planner()` method that reads the current planner state from `PlannerService` and produces a `HealthIssue` when the last planner run failed.

The issue SHALL use `category="planner"` and SHALL populate `code`, `details`, and `retry_in_s` from the planner service state. Severity SHALL be `critical` for config-blocking codes, `warning` otherwise.

`check_planner()` SHALL be invoked by `HealthChecker.check_all()` and the resulting issues SHALL appear in the `/api/health` response.

#### Scenario: Successful run produces no issue
- **WHEN** the last planner run succeeded
- **THEN** `check_planner()` returns an empty list

#### Scenario: Config-blocking failure produces critical issue
- **WHEN** the last planner run failed with code `EV_MISSING_POWER`
- **THEN** `check_planner()` returns a `HealthIssue` with `category="planner"`, `severity="critical"`, `code="EV_MISSING_POWER"`, and populated `details`
- **AND** the issue is visible in `/api/health` response

#### Scenario: Transient failure produces warning issue
- **WHEN** the last planner run failed with code `PRICES_UNAVAILABLE`
- **THEN** `check_planner()` returns a `HealthIssue` with `category="planner"`, `severity="warning"`, `code="PRICES_UNAVAILABLE"`, and a positive `retry_in_s`

### Requirement: Retry policy keyed on error code
`PlannerService` SHALL track retry state including `last_error_code`, `last_error_at`, `next_retry_at`, `consecutive_failures`, and `retry_suspended`. Retry cadence SHALL be determined by the last error code:

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
- **AND** automatic retries do not run until `settings_saved` is received

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
- **WHEN** `SchedulerService` reads `PlannerService.next_retry_at` and it is not `None`
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

### Requirement: Persistent error banner with details drawer
The frontend SHALL render planner failures as persistent banners using the existing `SystemAlert` component. The banner SHALL NOT be fully dismissible: users MAY collapse it to a single-line indicator, but a visible marker SHALL remain until the underlying failure clears.

The `SystemAlert` component SHALL render whenever `health.issues` contains one or more entries — regardless of the value of `health.healthy`. The previous guard `if (health.healthy) return null` SHALL be replaced with a check that returns null only when there are no issues to display.

When a `HealthIssue` carries a `details` payload, the banner SHALL render a "View details" control that opens a drawer component (`PlannerErrorDetails`) displaying:

- The error code as a monospace chip
- The human message and fix hint
- A diagnostics table of all key/value pairs from `details`
- A live retry countdown derived from `retry_in_s`, ticking down in real time and refreshing when a new health snapshot arrives
- A "Copy diagnostic bundle" button that copies a JSON blob of the full issue to the clipboard
- An "Open Settings" link when the error code is config-blocking

Secrets-bearing values in the diagnostic bundle (HA tokens, API keys) SHALL be redacted as `***` before being displayed or copied.

The transient 3-second toast previously shown in `QuickActions.tsx` for `planner_error` WebSocket events SHALL be removed. The frontend SHALL read planner state exclusively from the health endpoint/stream.

#### Scenario: Planner failure shows persistent banner
- **WHEN** the health endpoint returns an issue with `category="planner"` and severity `critical`
- **THEN** a persistent critical banner is rendered at the top of the application
- **AND** the banner remains visible across navigation

#### Scenario: Warning-level planner issue shows banner even when system is healthy
- **WHEN** the health endpoint returns `healthy=true` but `issues` contains a planner `severity="warning"` entry (e.g. `SOLVER_INFEASIBLE`)
- **THEN** the warning banner IS rendered (not suppressed)
- **AND** the banner displays the warning message and fix hint

#### Scenario: Banner cannot be hidden entirely
- **WHEN** the user clicks the collapse control on a planner error banner
- **THEN** the banner shrinks to a single-line indicator
- **AND** the indicator remains visible until the underlying failure clears

#### Scenario: Details drawer opens and shows diagnostics
- **WHEN** the user clicks "View details" on a planner error banner
- **THEN** a drawer opens showing the error code, message, fix hint, diagnostics table, and live retry countdown
- **AND** the "Copy diagnostic bundle" button copies a valid JSON string to the clipboard

#### Scenario: Retry countdown ticks live
- **WHEN** the drawer is open with `retry_in_s=90`
- **THEN** the displayed countdown decrements approximately once per second
- **AND** when a new health snapshot arrives with a different `retry_in_s`, the countdown resets to the new value

#### Scenario: Secrets are redacted in diagnostic bundle
- **WHEN** the diagnostic bundle is generated for copy-to-clipboard
- **THEN** any key matching known secret patterns (`*token*`, `*api_key*`, `*password*`) has its value replaced with `***`

#### Scenario: Toast for planner_error is removed
- **WHEN** a `planner_error` WebSocket event is received
- **THEN** no transient toast appears
- **AND** the persistent banner reflects the current planner state on the next health refresh

### Requirement: Battery config preflight reads correct field names
The battery config preflight check (`check_battery_config()`) SHALL read charge and discharge power limits from `battery.max_charge_w` and `battery.max_discharge_w` (stored in watts), converting to kW by dividing by 1000 before comparison.

The check SHALL NOT reference `battery.max_charge_power_kw` or `battery.max_discharge_power_kw` — these keys do not exist in the v2 config schema.

Checks: `capacity_kwh > 0`, `max_charge_w / 1000 > 0`, `max_discharge_w / 1000 > 0`, `min_soc_percent < max_soc_percent`.

#### Scenario: Valid battery config passes preflight
- **WHEN** `battery.capacity_kwh = 29`, `max_charge_w = 5000`, `max_discharge_w = 5000`, `min_soc_percent = 12`, `max_soc_percent = 100`
- **THEN** `check_battery_config()` raises no error

#### Scenario: Zero watts triggers invalid config error
- **WHEN** `battery.max_charge_w = 0`
- **THEN** `check_battery_config()` raises `CONFIG_INVALID`

#### Scenario: Missing watts field defaults to zero and triggers error
- **WHEN** `battery.max_charge_w` is absent from config
- **THEN** the field defaults to `0.0` and `check_battery_config()` raises `CONFIG_INVALID`

### Requirement: Planner service emits terminal phase on failure
`PlannerService` SHALL emit a `"failed"` progress phase via WebSocket immediately before clearing `_current_phase` in every error path (both typed `PlannerError` and untyped `Exception`). The `"failed"` phase SHALL be emitted before any state cleanup so the frontend receives a definitive terminal signal.

#### Scenario: Typed planner error emits failed phase
- **WHEN** the planner raises a `PlannerError` (e.g. `SOLVER_INFEASIBLE`)
- **THEN** the service emits a `planner_progress` WebSocket event with `phase="failed"`
- **AND** `_current_phase` is subsequently set to `None`

#### Scenario: Unexpected exception emits failed phase
- **WHEN** the planner raises an unhandled `Exception`
- **THEN** the service emits a `planner_progress` WebSocket event with `phase="failed"`
- **AND** `_current_phase` is subsequently set to `None`

#### Scenario: Successful run does not emit failed phase
- **WHEN** the planner completes successfully
- **THEN** the service emits `phase="complete"` and never emits `phase="failed"`

### Requirement: Frontend treats "failed" as a terminal planner phase
The `QuickActions` component SHALL handle `phase="failed"` as a terminal state equivalent to `phase="complete"`. When a `planner_progress` event with `phase="failed"` is received, the button text SHALL update to indicate failure and the planning state SHALL be cleared after a short delay so `isPlanning` returns to `false`. The `'failed'` phase SHALL NOT fall through to the generic `'Planning...'` default label.

#### Scenario: Failed phase shows failure label
- **WHEN** a `planner_progress` event with `phase="failed"` is received
- **THEN** the planner button shows a failure label (e.g. `"Failed ✗"`)
- **AND** the progress bar does not remain at a mid-run position

#### Scenario: Planning state clears after failed phase
- **WHEN** a `planner_progress` event with `phase="failed"` is received
- **THEN** `isPlanning` becomes `false` after a short delay
- **AND** the "Run Planner" button returns to its idle state
