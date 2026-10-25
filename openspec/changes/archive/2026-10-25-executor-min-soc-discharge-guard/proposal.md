# Proposal: executor-min-soc-discharge-guard

## Why

A Fronius user (19.2 kWh, min SoC 12 %, inverter reserve 5 %, build dev-261021.1943) saw SoC fall from 10.8 % to 6.9 % on 2026-10-24. Slots 12:00-12:15 and 13:30-13:45 planned 0.02-0.2 kWh of PV charge with no grid import. In `executor/controller.py` `_follow_plan`, the branch `elif slot.charge_kw > 0:` maps such a slot to `self_consumption` with no SoC check. PV was below load, so Fronius "Auto" covered the load from the battery. The planner never planned a discharge below min.

Deye is unaffected because `profiles/deye.yaml` writes `soc_target` in every mode (hardware floor). `profiles/fronius.yaml` only switches work mode and must never write `minimum_reserve`, so the executor is the only min_soc enforcement on Fronius and on any profile without a `soc_target` floor. This follows `min-soc-floor-tracking` (archive/2026-10-21-min-soc-floor-tracking), which bounded only the hold margin.

## What Changes

- A shared executor guard latches when live SoC (rounded int) is at or below `battery.min_soc_percent` and releases at `min_soc + 2` (`SOC_TRACKING_MARGIN`).
- While latched, plan-following decisions that resolve to `self_consumption` or `export` become `idle` (block discharge). `charge` and `idle` are unchanged.
- The latch persists across slots and replans as a `BatteryPlanState` field that `enter()` does not reset.
- With unreadable SoC (`soc_available` False) the latch keeps its previous state.
- The decision reason notes the guard (new constant, like `HOLD_MARGIN_REASON`).
- Planner, profiles and config are unchanged.

## Capabilities

### Modified Capabilities
- `battery-plan-tracking`: new requirement for the min-SoC discharge guard; the hold-margin requirement now releases at `min_soc + 2` near the minimum.

## Impact

- `executor/controller.py` (`_follow_plan`, new reason constant, `BatteryPlanState` latch field). `executor/engine.py` is unchanged: it already shares one `BatteryPlanState` with the main tick.
- Tests: `tests/executor/test_battery_plan_tracking.py`, `tests/executor/test_executor_engine.py` (EV isolation re-decide above min SoC).
- No config, API, UI, schema or dependency changes. Fronius "Block Discharging" still charges from PV, so PV surplus still reaches the battery while latched.
