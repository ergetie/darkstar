## Why

Two PV-charging defects in the executor controller (`executor/controller.py`), both found on Deye hardware.

1. **Battery feeds the EV in PV-charge slots.** `_follow_plan` orders its branches export (L259) > grid charge (L261-266) > `elif slot.charge_kw > 0` (L267-270, `self_consumption`) > `ev_isolating` (L271-278, `idle`). A slot that plans PV charging while EV source isolation is active (`discharge_blocked_by_ev`, set by the engine for planned, manual, unplanned and surplus EV charging; `executor/engine.py` ~L1932) hits the PV-charge branch before the isolation branch. It selects `self_consumption`, so when PV drops below house plus EV load the battery discharges into the car. The earlier change `fix-ev-isolation-slot-and-water-state` made isolation idle every slot except this one.
2. **PV charging is capped at the planned kW even when no export is planned.** `_calculate_charge_limit` (L418) returns the planned `charge_kw` as `charge_value` whenever `charge_kw > 0`. Deye `self_consumption` writes `max_charge_current = {{charge_value}}` (`profiles/deye.yaml` ~L141, comment "Limit PV charging current to enable excess export", from commit 19cbbe9e, 2026-03-05). In every PV-charge slot the charge current is capped at the plan, and PV above the forecast is exported instead of stored. Slots with `charge_kw <= 0` already get max charge (`_follow_plan` ~L338-342).

## What Changes

- In the PV-charge branch, select `idle` when `ev_isolating`, else `self_consumption`. `plan_state.enter(None, None)` either way. Add a reason note (new constant, same pattern as `HOLD_MARGIN_REASON`) so the Executor page shows why.
- For `self_consumption`, use the user's maximum charge value (`max_charge`) when the slot plans no export (`export_kw <= 0`). Cap at the planned charge value only when the slot plans export (`export_kw > 0`). Implemented generically in the controller, no profile-specific code.
- Grid-charge branch, export branch, `charge` mode values and the min-SoC guard are unchanged.
- Accepted residuals, no profile changes: Deye idle keeps `max_discharge_current` 15 A (intentional, EN50549), Sungrow idle keeps `max_discharge_power` 10 W. Fronius idle (Block Discharging) and Deye idle allow PV charging (confirmed on Deye hardware).

## Capabilities

### Modified Capabilities
- `executor`: default `self_consumption` PV charging uses max charge unless export is planned (modified requirement); EV isolation and normal charge mode requirements restate the idle outcome in PV-charge slots (modified requirements).
- `battery-plan-tracking`: EV source isolation idles the battery in PV-charge slots too (modified requirement); solar-only scenario scoped to non-isolated slots (modified requirement).

## Impact

- `executor/controller.py` only (`_follow_plan`, one new reason constant).
- Tests: `tests/executor/test_ev_isolation.py`, `tests/executor/test_executor_controller.py`, `tests/executor/test_battery_plan_tracking.py`, plus a Deye profile action check.
- No config, API, schema, profile, frontend or dependency changes.
- Behavior change to note: with no planned export, Deye (the only profile using `{{charge_value}}` in `self_consumption`) will no longer export PV above the planned charge during PV-charge slots; the battery takes it, up to `max_charge_current`.
