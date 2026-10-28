## Why

A user with battery SoC at 6% cannot use the water heater boost button: the executor cancels the boost on the next tick and sends a "battery too low" notification (`executor/engine.py` ~1751-1775, added in abf7efe4 with the rationale "protect battery"). The guard protects nothing: the boost override runs in `idle` (battery discharge blocked), so boost always heats from grid or PV, exactly like EV source isolation. Decision: a manual boost must never be blocked or cancelled based on battery SoC.

## What Changes

- Remove the low-SoC check (`SoC < min_soc + 10`), the boost clear and the cancellation notification from the executor's boost branch; an active manual boost always yields the FORCE_HEAT override.
- Change the boost override `soc_target` from `max(int(SoC - 10), int(min_soc + 10))` to the current plan slot's `soc_target`, the same value EV isolation and hold slots write in idle (fallback without a plan: live SoC, at least `min_soc_percent`; see design.md).
- **BREAKING** (behavioral): the "boost cancelled - battery too low" notification no longer exists.
- Replace the executor spec requirement "Boost-cancellation notification is delivered" with "Manual water boost is never cancelled by battery SoC".
- Replace `test_boost_cancelled_notification_is_awaited` with regression tests.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `executor`: remove the low-SoC boost-cancellation notification requirement; add the SoC-independent manual boost requirement (idle, no discharge, plan-slot soc_target).

## Impact

- `executor/engine.py` (boost override branch only).
- `tests/executor/test_executor_engine.py` (replace one test, add regression tests).
- `openspec/specs/executor/spec.md` (via delta). No other spec conflicts found (water-heater-execution, per-device-water-boost, battery-plan-tracking contain no SoC-cancel text). Frontend `CommandBar.tsx` has no SoC-cancellation text (only the manual "Water Boost Cancelled" toast for the user's own cancel), so no frontend change.
- No config, schema, API or dependency changes.
