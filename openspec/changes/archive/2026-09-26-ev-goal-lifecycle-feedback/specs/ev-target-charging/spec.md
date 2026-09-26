## MODIFIED Requirements

### Requirement: Read-only API exposes per-charger goal and progress
A `GET /api/ev/chargers` endpoint SHALL return, per charger, live HA sensor data merged with the goal and progress from the last pipeline run. The endpoint SHALL report the goal for as long as the planner would act on it (goals are durable user intent, not a cache): there SHALL be no time-based nulling of an active goal. The response SHALL include `last_planned_at` so the UI can indicate when the planner last ran, SHALL include `n_days` for `every_n_days` goals, and SHALL include `plan_pending` (bool): true when a goal-triggered planner run for the charger is queued or running, or when the goal was edited after `last_planned_at` and no goal-triggered run for that edit has since failed; false otherwise. The response SHALL include `assumed_plugged` (bool), true when the last plan scheduled goal charging for a charger that is still unplugged, and `planned_start` (ISO datetime or null), the start of the charger's first not-yet-ended slot with planned charging.

#### Scenario: Charger with an active goal
- **WHEN** a plugged charger has a goal and the pipeline has run
- **THEN** the response SHALL include:
  - live `plugged_in` / `soc_percent` / `power_kw`;
  - the goal: `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `anchor_date`, and the resolved `deadline`;
  - `required_kwh` / `delivered_kwh` / `remaining_kwh`;
  - `planned_by_day` (a list of `{date, kwh, basis}`) and `deferral_price_source`;
  - `last_planned_at`;
  - `plan_pending`, `assumed_plugged` and `planned_start`;
  - `status ∈ {on_track, behind, complete, idle}`.
- **AND** the response SHALL NOT include `daily_quota_kwh` or `quota_schedule`

#### Scenario: Planner has not run recently
- **WHEN** a goal exists but the pipeline has not run for hours
- **THEN** the goal SHALL still be returned (matching what the planner will act on)
- **AND** `last_planned_at` SHALL show the stale timestamp instead of the goal being nulled

#### Scenario: Pipeline state missing
- **WHEN** the state file is missing or unreadable
- **THEN** chargers SHALL be returned with `status: "idle"` and null goal-progress fields
- **AND** live HA sensor data SHALL still be populated

#### Scenario: Goal edited after the last plan
- **WHEN** the goal's `last_updated` is later than `last_planned_at`
- **THEN** `plan_pending` SHALL be true

#### Scenario: Plan caught up
- **WHEN** a planner run completes after the last goal edit
- **THEN** `plan_pending` SHALL be false

#### Scenario: Goal saved early in a planning slot
- **WHEN** a goal is saved a few seconds after a 15-minute slot starts and a planner run then reads it in the same slot
- **THEN** `last_planned_at` SHALL be the wall-clock time at which that run read the goals, not the slot start
- **AND** `plan_pending` SHALL be false once that run completes

#### Scenario: Goal edited during a planner run
- **WHEN** the goal is edited after a running planner run read the goals
- **THEN** `plan_pending` SHALL stay true after that run completes, until a later run reads the edited goal

#### Scenario: Goal-triggered run fails
- **WHEN** the goal-triggered planner run fails
- **THEN** `plan_pending` SHALL be false once the failure is reported
- **AND** `last_planned_at` SHALL remain the previous successful run's timestamp
