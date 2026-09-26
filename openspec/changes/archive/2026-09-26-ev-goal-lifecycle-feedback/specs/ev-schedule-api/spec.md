## ADDED Requirements

### Requirement: Write endpoint maintains a stable every-N-days anchor
When the write endpoint persists a goal with `repeat: "every_n_days"`, it SHALL set `anchor_date` to the current local date if the goal had no `anchor_date`, or the repeat mode changed to `every_n_days`, or `n_days` changed. Otherwise it SHALL preserve the existing `anchor_date` (saving other fields such as target SoC or ready-by time SHALL NOT move the cycle). `anchor_date` SHALL be returned by `GET /api/ev/chargers` and preserved by planner writebacks. When the goal is cleared or its repeat mode changes away from `every_n_days`, `anchor_date` SHALL be removed.

#### Scenario: New every-3-days goal
- **WHEN** the user saves `repeat: every_n_days`, `n_days: 3` on 2026-09-25
- **THEN** `anchor_date` SHALL be persisted as 2026-09-25

#### Scenario: Target changed on an existing every-N-days goal
- **WHEN** the user changes only the target SoC of an every-3-days goal anchored on 2026-09-20
- **THEN** `anchor_date` SHALL remain 2026-09-20

#### Scenario: n_days changed
- **WHEN** the user changes `n_days` from 3 to 2 on 2026-09-25
- **THEN** `anchor_date` SHALL become 2026-09-25

### Requirement: Write endpoint triggers an immediate replan
After persisting a goal set or clear, the write endpoint SHALL request a goal-change replan (fire-and-forget, subject to coalescing and debounce) before returning. The response SHALL NOT wait for the planner and SHALL report `plan_pending: true` for the charger.

#### Scenario: Save returns before the plan
- **WHEN** a goal is saved while the solver takes 20 seconds
- **THEN** the endpoint SHALL respond without waiting for the solve
- **AND** the returned charger state SHALL have `plan_pending: true`
