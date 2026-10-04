## ADDED Requirements

### Requirement: Failed plan save is surfaced as a warning
When storing the plan to `slot_plans` fails during a planner run, the system SHALL log the failure at error level with the exception, SHALL record it as the current plan save failure, and SHALL NOT fail the planner run or prevent `schedule.json` from being written. While a plan save failure is recorded, `HealthChecker.check_planner()` SHALL return a `HealthIssue` with `category="planner"`, `severity="warning"` and `code="PLAN_STORE_FAILED"`, which SHALL appear in the `/api/health` response. A later successful plan save SHALL clear the recorded failure. `PLAN_STORE_FAILED` SHALL be a warning-only code: it SHALL NOT count as a consecutive failure and SHALL NOT change the retry cadence.

#### Scenario: Save failure produces a health warning
- **WHEN** a planner run writes `schedule.json` but `store_plan` raises an exception
- **THEN** the run still reports success
- **AND** `check_planner()` returns a warning `HealthIssue` with `code="PLAN_STORE_FAILED"`
- **AND** the failure is logged at error level

#### Scenario: Next successful save clears the warning
- **GIVEN** a plan save failure is recorded
- **WHEN** a later planner run stores its plan successfully
- **THEN** `check_planner()` no longer returns a `PLAN_STORE_FAILED` issue

#### Scenario: Save failure does not affect retry state
- **WHEN** a plan save fails during an otherwise successful run
- **THEN** `consecutive_failures` stays 0 and `retry_suspended` stays `False`
