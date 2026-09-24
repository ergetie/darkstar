## Why

On 2026-09-24 a goal (53% → 55% by 10:30) was missed: the go-e dropped offline 10:14:50–10:21:45, charging ran only ~8 of the planned 15 minutes at 6 A (~4.1 kW instead of the planned 4.8 kW), and at 10:30 Darkstar stopped with the car still plugged in at 53%. Nothing recovered the deficit. Several independent gaps combined: the in-progress slot is planned as a full slot, planned kW is floored to amps, charging is forbidden after the deadline, a charge failure never triggers a replan, and an unreachable charger is indistinguishable from an unplugged car.

## What Changes

- **Missed-goal grace window**: when a deadline passes, the car is still plugged in and SoC is below target, the goal stays active for a configurable grace period (`ev_chargers[].missed_goal_grace_hours`, default 4) with a new effective deadline of `missed_deadline + grace`. The solver plans the remainder in the cheapest slots in that window (soft, same shortfall mechanism as a normal goal). After the grace window, the goal is dropped as today.
- **Partial current slot**: the planner SHALL use the remaining duration of the in-progress slot (from `now` to slot end) as that slot's energy capacity for EV charging, so energy that no longer fits is moved to later slots or planned at higher power.
- **Amps rounding**: the plan-derived ampere setpoint SHALL be rounded **up** (`ceil`) instead of down, clamped to `[min_current_a, max_current_a]`, so delivered power is never below planned power. **BREAKING** (behavioural): setpoints may be 1 A higher than before.
- **Replan on charge failure**: when EV charge-failure detection fires (commanded charging, ~0 kW actual) the executor SHALL request a replan, with its own 5-minute cooldown (independent of the balancer replan limit), and SHALL request one again when actual power resumes after a failure, so remaining time is re-planned.
- **Charger unreachable state**: when the charger's plug sensor or switch entity is `unavailable`/`unknown`, the charger SHALL be reported as *unreachable* (logs, EV API, dashboard) rather than "unplugged", and the missed-goal grace logic SHALL treat an unreachable charger as still plugged in.

## Capabilities

### New Capabilities
- `ev-missed-goal-recovery`: grace window that keeps a missed goal active while plugged in, and the unreachable-charger state that feeds it.

### Modified Capabilities
- `ev-current-control`: plan-derived setpoint rounds up instead of floor.
- `ev-target-charging`: in-progress slot uses remaining duration for EV energy; the post-deadline zero-charging rule is relaxed during a grace window.
- `ev-charge-failure-detection`: failure (and recovery after failure) triggers a rate-limited replan.

## Impact

- `planner/pipeline.py` (goal/deadline resolution, grace window, partial-slot duration), `planner/solver/kepler.py` (deadline constraint, first-slot capacity), `backend/core/ev_goal.py`.
- `executor/load_balancer.py` (`planned_kw_to_amps`), `executor/engine.py` (failure → replan, unreachable state), `backend/ha_socket.py` (unavailable ≠ unplugged).
- EV API / dashboard EV card: new `unreachable` and `grace` status fields.
- `config.default.yaml`: new `missed_goal_grace_hours` per charger. No new dependencies, no DB schema change.
