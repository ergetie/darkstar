# Tasks

## 1. Executor sensor reading

- [x] 1.1 Skip `water_temp` read when the first water heater device has `control_type: switch` in `_gather_system_state`. Verify: test with switch heater logs no warning and issues no read of the target entity for temperature.
- [x] 1.2 Add per-sensor safe parse helper with per-entity rate-limited warning (entity id + reason); use it for all numeric reads. Verify: unit test of helper (returns None, logs once within interval).
- [x] 1.3 Make the phase-current block independent of other parse failures (own try/except backstop). Verify: test where another sensor is non-numeric still yields `grid_current_a`.

## 2. Load balancer messages

- [x] 2.1 Add stale-phase description (L-labels, "no reading" vs real age) and use it in `_resolve_ev` messages; label stale-since as pause duration. Verify: updated tests in tests/executor/test_load_balancer*.py assert new text.
- [x] 2.2 Grep tests and frontend for old "Phase sensor(s)" strings and update. Verify: `grep -rn "Phase sensor(s)"` shows only new format.

## 3. Regression tests

- [x] 3.1 Add torleif test: switch heater (target switch.vvb state "on") + live L1-L3 sensors, assert state.grid_current_a populated and balancer does not report stale. Verify: fails before the fix, passes after.
- [x] 3.2 Add temperature-heater test keeping `current_water_temp` parse. Verify: test passes.
- [x] 3.3 Run `./scripts/lint.sh` and the executor tests. Verify: all green.
