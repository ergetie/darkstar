## 1. Slot preservation during isolation

- [x] 1.1 In `executor/engine.py` (~1929-1940) replace the manual `SlotPlan(...)` rebuild with `dataclasses.replace(slot, discharge_kw=0.0, discharge_blocked_by_ev=True)`; import `replace` from `dataclasses` per file style.
- [x] 1.2 Test (`tests/executor/test_ev_isolation.py`): generic over `dataclasses.fields(SlotPlan)` with non-default values, every field except `discharge_kw` and `discharge_blocked_by_ev` is preserved. Replace the simulated-rebuild test `test_slot_reconstruction_preserves_all_fields` (~line 325) with one that exercises the engine path.
- [x] 1.3 Tests (engine-level, per-device switch heater `control_type: switch`): planned EV + water plan keeps heater on; active manual charge + water plan keeps heater on; actual unplanned charging + water plan keeps heater on; keep-on and surplus cases likewise.

## 2. Controller idles for every isolation trigger

- [x] 2.1 In `executor/controller.py` (~247-249) add `or slot.discharge_blocked_by_ev` to the `ev_isolating` condition; update the comment at the idle branch (~265-268).
- [x] 2.2 Tests in `tests/executor/test_ev_isolation.py` (controller class): manual charge, actual-only, and surplus-only isolated slots (`ev_charging_kw=0`, no keep-on, `discharge_blocked_by_ev=True`) with live SoC above `soc_target` give mode `idle`; planned grid charge below target still gives charge; a non-isolated hold slot is unchanged.

## 3. No fake water temperature

- [x] 3.1 `executor/override.py:77`: `current_water_temp: float | None = None`; fix any type-checker fallout at readers.
- [x] 3.2 Confirm by grep that `executor/engine.py:3181` is the only consumer; keep `_safe_float` behavior at ~2879-2881 (failed read leaves `None`).
- [x] 3.3 Tests: update `tests/executor/test_robust_sensor_reading.py:108` (default is now `None`); add switch heater records `before_water_temp` None; failed read records None; successful read still records the value (55.5).

## 4. Executor page display

- [x] 4.1 `frontend/src/pages/Executor.tsx`: `before_water_temp?: number | null` (~123); in the render (~1474) show `N°C` when a number, else the On/Off from the first `water_switch` entry's `previous_value` in `action_results` (label "Water Heater"), else "—" with no unit. Use existing design-system tokens per `docs/design-system/AI_GUIDELINES.md`.
- [x] 4.2 Tests in `frontend/src/pages/Executor.history.test.tsx`: switch heater shows On/Off and no `°C`; failed temperature read shows "—" only; numeric reading shows `°C`.

## 5. Verification

- [x] 5.1 Run the affected tests with `UV_NO_SYNC=1 uv run python -m pytest tests/executor/test_ev_isolation.py tests/executor/test_robust_sensor_reading.py tests/executor -q`, the frontend test file, then `./scripts/lint.sh`.
- [x] 5.2 Run `openspec validate fix-ev-isolation-slot-and-water-state --strict`.
