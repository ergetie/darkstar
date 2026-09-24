## 1. Amps rounding (ev-current-control)

- [x] 1.1 Change `planned_kw_to_amps` in `executor/load_balancer.py` to ceil with epsilon, keep clamp and `None` below min
- [x] 1.2 Update the docstring and any test expectations for floor behaviour (e.g. 11 kW → 16 A)
- [x] 1.3 Add tests: 4.8 kW/3ph → 7 A, 4.14 kW/3ph → 6 A, clamp at max_current_a

## 2. Partial in-progress slot (ev-target-charging)

- [x] 2.1 Pipeline: compute `first_slot_remaining_h` from `now` and pass it into the Kepler input
- [x] 2.2 Kepler: use `h_ev = min(h, first_slot_remaining_h)` for slot 0 EV min/max energy bounds
- [x] 2.3 Kepler: report slot-0 EV kW as `ev_energy / h_ev` in the result
- [x] 2.4 Tests: replan 7 min into slot caps EV energy; boundary replan unchanged

## 3. Missed-goal grace window (ev-missed-goal-recovery)

- [x] 3.1 Add `missed_goal_grace_hours` (default 4) to the EV charger config model and `config.default.yaml`
- [x] 3.2 Add `resolve_previous_ready_by` in `backend/core/ev_goal.py` (all repeat types incl. `none`)
- [x] 3.3 Pipeline: when previous deadline is within grace, plugged/unreachable, SoC < target → effective deadline = min(missed + grace, next ready-by); log it
- [x] 3.4 Ensure Kepler deadline-zero rule and shortfall constraint use the effective deadline
- [x] 3.5 Tests: goal missed + plugged → grace deadline; expired; unplugged; grace=0; capped by next ready-by
- [x] 3.6 Settings UI: expose `missed_goal_grace_hours` per charger (design-system compliant)

## 4. Unreachable charger state (ev-missed-goal-recovery)

- [x] 4.1 `backend/ha_socket.py`: classify `unavailable`/`unknown` plug state as unreachable; keep last known plug state; no unplug replan
- [x] 4.2 Executor/pipeline: propagate unreachable flag in charger state; planner uses last known plug state
- [x] 4.3 EV API: add `unreachable` field; dashboard EV card shows "Charger unreachable"
- [x] 4.4 Tests: unavailable does not replan/unplug; return to connected triggers plug-in replan

## 5. Failure/recovery replan (ev-charge-failure-detection)

- [x] 5.1 In `_check_ev_charge_failure`, request `scheduler_service.trigger_now()` on first failure per period
- [x] 5.2 Request a replan on first >0.1 kW after a detected failure
- [x] 5.3 Own 5-minute cooldown for failure/recovery replans, independent of the `_track_balancer_throttling` rate limit
- [x] 5.4 Tests: failure replans, recovery replans, cooldown respected, independent of balancer limit
- [x] 5.5 Recovery inside the cooldown stays pending and fires after the cooldown (not dropped); tests

## 6. Verification

- [x] 6.1 Run `./scripts/lint.sh` and full test suite
- [x] 6.2 Replay the 2026-09-24 scenario in a test: offline 10:14–10:21, 55% by 10:30 → recovers in grace window
