## Why

In hold slots (planned `discharge_kw == 0`, no EV isolation) the battery SoC ratchets down while the plan says it should stay put. Observed on 2026-10-25 (Fronius, bundle `darkstar-diagnostics-dev-261021.1943-20261025-163017-kristofer3`): SoC fell 96% to 89% over 15:30-17:17 with PV near 0 and zero planned discharge (about 1.06 kWh of battery discharge into house load), with 12 Auto/Block Discharging mode changes per hour.

Cause, verified in code:

- The planner replans every 30 minutes (cadence only), seeds SoC from live Home Assistant (`planner/pipeline.py` ~L1459) and sets every hold slot target to the entry SoC (`planner/output/soc_target.py`, hold slot final pass).
- The planner models a hold slot as load served from the grid (discharge 0). It models no drift.
- The executor hold branch (`executor/controller.py` L287-293) calls `plan_state.enter("hold", soc_target)` then `_hold_mode`, which runs `self_consumption` until SoC <= target - 2 (`SOC_TRACKING_MARGIN`), then latches idle and releases at live SoC >= target.
- `BatteryPlanState.enter` (L56-62) clears the latch whenever the target changes. Each replan lowers the target to the new, lower entry SoC and re-arms a fresh 2-point margin, so the SoC steps down 2 points per replan. A release at `live_soc >= target` with a PV flicker also flips modes repeatedly.

The plan is holding because of a price-reserve terminal floor (100%, from 2026-10-27 forecast prices). That is correct behaviour and out of scope. PV forecast was about 2.5x under actual that day, so a fix gated on the PV forecast would be wrong in both directions. The fix must not depend on forecasts.

## What Changes

- A hold slot means "no battery discharge; PV may still charge the battery; grid covers the load", matching what the planner modeled. The executor selects `idle` in every hold slot (no EV isolation) at every SoC.
- Remove the 2-point hold margin, the hold floor and the hold latch (`_hold_mode`, hold use of `BatteryPlanState.latched`). A hold block no longer carries state, so replans cannot re-arm anything.
- Rename `HOLD_MARGIN_REASON` ("hold margin used, blocking discharge") to a reason that is true for every hold tick (new `HOLD_REASON`).
- Unchanged: charge-target latch and its 2-point resume, min-SoC guard latch, EV isolation branches, discharge-slot-at-floor branch, planner, profiles, config, frontend.

## Capabilities

### Modified Capabilities
- `battery-plan-tracking`: requirement "Hold slots use a 2-point margin" is replaced by "Hold slots block battery discharge" (REMOVED + ADDED).

## Impact

- `executor/controller.py`: hold branch in `_follow_plan`, `_hold_mode` deleted, reason constant renamed, comments on `SOC_TRACKING_MARGIN` and `BatteryPlanState`.
- `executor/config.py` comment on `min_soc_percent` (no longer bounds a hold margin).
- `executor/override.py` / `executor/engine.py` comments mentioning the hold margin.
- `tests/executor/test_battery_plan_tracking.py` (`TestHoldMargin`, `TestHoldFloorAtMinSoc` rewritten; regression test added).
- Behaviour change to note: hold slots no longer let the battery cover the first 2 points of a PV shortfall; the grid covers it. This reverses the user-facing choice recorded in archived change `battery-soc-plan-tracking` D2 (it favoured using the battery at an expensive price); see design open questions.
- No config, API, schema, profile, planner, frontend or dependency changes.
