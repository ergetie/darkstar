## 1. Phase controller

- [x] 1.1 Add `skip_hold: bool = False` to `PhaseModeController.decide()` in `executor/ev_surplus.py`; when true, bypass the target-hold gate but keep the since-last-switch gate, hysteresis threshold, relief hold and fail-safe
- [x] 1.2 Unit tests: planned target switches immediately; since-last-switch gate still blocks; default behavior unchanged

## 2. Next-slot lookup

- [x] 2.1 Extend `_load_current_slot` in `executor/engine.py` to also parse the slot immediately after the current one and store it on the engine for the tick (None if absent or schedule stale)
- [x] 2.2 Tests: next slot found, last slot has no next, stale schedule yields None

## 3. Planned targets and idle look-ahead

- [x] 3.1 In `_update_ev_surplus_and_phase_mode`, pass `skip_hold=True` when the target is the planned kW
- [x] 3.2 Idle look-ahead: if no manual, not surplus-eligible, not keep-on-only and current planned kW ≤ 0.1, use next slot's planned kW (> 0.1) as target with `skip_hold=True`
- [x] 3.3 Confirm the balancer does not command charging current during a pre-switch
- [x] 3.4 Engine tests covering all scenarios in `specs/ev-phase-switching/spec.md`, including the 2026-09-27 case

## 4. Failure grace window

- [x] 4.1 In `_check_ev_charge_failure`, skip incrementing (without resetting) the zero-power counter when a commanded charger's `last_switch_time` is within `PHASE_SWITCH_SETTLE_S`
- [x] 4.2 Tests covering all scenarios in `specs/ev-charge-failure-detection/spec.md`

## 5. Ramp-up hold-off

- [x] 5.1 In `executor/load_balancer.py`, record `_ev_reduced_at[charger_id]` on every setpoint reduction (throttle, floor degrade, relief); clear it on plan end and pause
- [x] 5.2 Refuse the ramp-up path while `now - _ev_reduced_at < ramp_up_window_s`, returning the existing "Holding" output
- [x] 5.3 Tests covering all scenarios in `specs/phase-load-balancing/spec.md`, including a replay of the 12:39–12:40 sawtooth

## 6. Verify

- [x] 5.1 Run `./scripts/lint.sh` and the full test suite
- [x] 5.2 `openspec validate ev-planned-phase-switching`
