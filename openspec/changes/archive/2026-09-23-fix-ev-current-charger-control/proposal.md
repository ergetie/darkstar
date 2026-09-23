## Why

A live test on production (2026-09-23) showed that scheduled charging on a `type: current` EV charger (go-e) never starts, and when it fails nothing explains why:
- The executor never switches the charger to its "charging enabled" value. It only writes amps, so the go-e stayed on `dont_charge`.
- Stopping writes 0 A, which Home Assistant rejects with HTTP 500 because the entity minimum is 6 A. That causes a retry storm and 7 s executor ticks.
- Failed EV actions are never written to the execution log.
- A goal that gets zero charging, because the 8 kW grid limit left no room, only produces a vague log warning while the UI shows "ON TRACK".
- Every planner run silently hits the hardcoded 30 s solver time limit.

## What Changes

- **Current-type charger switch control**: to start charging, the executor sets the charger's control entity (`switch_entity`) to the user-configured `charge_enabled_value`, then writes the ampere setpoint. To stop or pause, it sets `switch_entity` to the configured `charge_disabled_value` and never writes 0 A or anything below `min_current_a`. Nothing is hardcoded.
- **BREAKING**: `type: current` chargers MUST have a `switch_entity` configured. This is validated in the backend and enforced in the settings UI.
- **EV action logging**: every EV action (switch on/off, current setpoint, stop, phase-mode switch) is written to the execution log whether it succeeds or fails. Each record includes the charger id, the value sent (amps or option) and the error details. Consecutive identical failures are deduplicated.
- **Failure backoff**: after a failed EV write, the executor backs off writes to that charger instead of retrying on every tick, so a failing charger cannot stall the executor loop.
- **Debug output**: failure logs include the attempted value, and the misleading success wording in failure messages is fixed.
- **Execution log UI**: badges for EV actions and a source filter (All / Inverter / EV). The history API gets a matching `source` parameter.
- **Goal shortfall diagnostics**: the planner persists per-charger scheduled kWh, shortfall kWh and a reason code (`grid_limit`, `deadline_too_close`, `cost_tradeoff`) with the schedule. The EV API reports an `at_risk` status using these values, and the EV card shows the shortfall and a plain-language reason instead of "ON TRACK".
- **Solver time limit**: the limit is configurable through `kepler.solver_time_limit_s` (default 60, was hardcoded 30) and exposed in settings. When the solver stops at the limit, the planner logs a warning and flags the result, even if the solver reports the result as optimal.
- Non-goal: battery source isolation stays a full discharge block while the EV charges, as decided by the user.

## Capabilities

### New Capabilities
- `ev-goal-shortfall-diagnostics`: per-charger scheduled/shortfall/reason computed by the planner, persisted, exposed by the EV API and shown on the EV card.

### Modified Capabilities
- `ev-current-control`: actuation starts and stops via the configured switch values. The pause behaviour for "below the minimum current" uses the switch instead of a 0 A write. `switch_entity` is required.
- `executor`: all EV actions are logged whether they succeed or fail, with deduplication and per-charger failure backoff. History can be filtered by `source`.
- `planner`: configurable solver time limit, default 60 s, with detection when the limit is hit.

## Impact

- Backend: `executor/engine.py` (`_control_ev_charger_current`, binary switch path, phase-mode path), `executor/actions.py`, `executor/config.py` (validation), `executor/history.py`, `backend/api/routers/executor.py`, `backend/api/routers/ev.py`, `planner/pipeline.py`, `planner/solver/kepler.py`, `planner/solver/adapter.py`, `planner/solver/types.py`, schedule persistence.
- Frontend: `frontend/src/pages/Executor.tsx`, `frontend/src/components/EVChargingCard.tsx`, settings EV charger editor (switch required for current type), solver time-limit field, `config-help.json`.
- Config: `config.default.yaml` gains `kepler.solver_time_limit_s: 60`. Existing `type: current` chargers without `switch_entity` fail validation until one is configured.
- No DB schema change: EV records reuse the existing `execution_log` columns (`source="ev_charger"`).
- A planner run can now take up to about 60 s longer. No backend timeouts depend on the run duration.
