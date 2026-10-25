## Why

A user with a switch-controlled water heater (`switch.vvb`, `control_type: switch`) had the heater off in 103 of 103 slots that planned both water heating and EV charging since 2026-09-30. On 2026-10-24 01:45 `switch.vvb` was turned off in the same tick EV source isolation started, while 3.1 kW of water heating was planned.

Root cause: during EV source isolation `ExecutorEngine` rebuilds the `SlotPlan` by hand (`executor/engine.py`) and copies only some fields. `water_heater_plans` and `water_heating_boost` are dropped. The rebuilt slot is passed to `make_decision` (`executor/engine.py`), so `Controller._determine_water_temps` (`Controller._determine_water_temps`) finds an empty plan and gives every per-device heater `temp_off`. The dispatcher then switches the heater off (`executor/engine.py:2106-2132`). `ev_charger_plans`, `ev_surplus_kw`, `custom_entity_active`, `soc_entry`, `slot_start` and `slot_end` are dropped too; nothing reads them from the rebuilt slot today, but they must not be lost.

Two related defects found during the investigation:

- Isolation also triggers for a manual EV charge, actual unplanned charging and surplus eligibility. In those cases the slot has `ev_charging_kw = 0` and no keep-on, so the controller's `ev_isolating` test (`Controller._follow_plan`) is false. With `discharge_blocked_by_ev=True` it skips the hold branch and selects `self_consumption` when live SoC is above `soc_target`, so the battery can feed the car.
- `SystemState.current_water_temp` defaults to `50.0` (`executor/override.py:77`). A switch heater is never read for temperature (`executor/engine.py:2738-2747`) and a failed read keeps the default (`executor/engine.py:2879-2881`). The fake 50 is stored as `before_water_temp` (`executor/engine.py:3181`) and shown on the Executor page under "State before execution -> Water Temp" (`frontend/src/pages/Executor.tsx:1474`). Display only; no decision uses it.

## What Changes

- Build the isolated slot with `dataclasses.replace(slot, discharge_kw=0.0, discharge_blocked_by_ev=True)` so every other field is preserved. Water heaters follow their plan during isolation for every trigger: planned EV, keep-on, manual charge, actual unplanned charge, surplus.
- The controller treats `slot.discharge_blocked_by_ev` as isolation: `ev_isolating` includes it, so the mode is `idle` whenever isolation is active, whatever triggered it.
- `SystemState.current_water_temp` becomes `float | None`, default `None` (no reading). Failed reads keep `None`. `before_water_temp` is recorded as `None` (column already nullable, no migration).
- Executor page: on/off (switch) heaters show their before-switch state (On/Off) in "Water Temp"; temperature heaters with no reading show a bare "—" (no unit).
- Trigger conditions for isolation are unchanged.

## Capabilities

### Modified Capabilities
- `executor`: EV source isolation preserves the full slot plan (new requirement); water-temperature state has no fake default (modified requirement); Executor page before-state display for switch heaters (new requirement).
- `battery-plan-tracking`: EV source isolation always idles the battery (new requirement).

## Impact

- `executor/engine.py` (isolation slot, before-state recording), `executor/controller.py` (`ev_isolating`), `executor/override.py` (`current_water_temp` default and type), `frontend/src/pages/Executor.tsx` (type and render).
- Tests: `tests/executor/test_ev_isolation.py`, `tests/executor/test_robust_sensor_reading.py` (line 108 asserts the old 50.0 default), `frontend/src/pages/__tests__/Executor.history.test.tsx`.
- No config, API, schema, migration or dependency changes. No changes to inverter profiles (their idle actions differ but stay as is).
- Out of scope: tank temperature sensor for on/off heaters (`docs/BACKLOG.md:98`), other `SystemState` defaults (soc 50, pv/load 0), changing isolation trigger conditions.
