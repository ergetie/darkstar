## Context

`PhaseModeController.decide()` (`executor/ev_surplus.py`) applies two gates before switching, both using `min_dwell_s` (default 600 s):

1. **Target-hold gate** — the target power must stay on one side of the 3-phase threshold for `min_dwell_s`.
2. **Since-last-switch gate** — at least `min_dwell_s` since the previous switch (contactor protection).

`_update_ev_surplus_and_phase_mode()` (`executor/engine.py`) derives the target from one of: manual charge, surplus, keep-on-only, or the planned `ev_charger_plans` kW. An idle charger gets target 0, which drifts it to 1-phase after 600 s.

`_check_ev_charge_failure` counts ticks with commanded charging and <0.1 kW actual; 5 ticks (25 s) raises a failure notification and replan. The go-e pauses ~25 s after a phase change (observed 2026-09-27 on prod).

`PHASE_SWITCH_SETTLE_S = 60` already exists in `engine.py` for balancer phase attribution after a switch.

## Goals / Non-Goals

**Goals:**
- Planned targets switch at the slot boundary.
- Idle chargers pre-switch for the next planned slot.
- No false failure notification from a commanded phase switch.

**Non-Goals:**
- Changing surplus-driven switching or balancer relief behavior.
- Looking further ahead than one slot.
- Making the grace window configurable.

## Decisions

**D1 — Target-hold gate is skipped for planned targets only.** `decide()` gets a `skip_hold: bool = False` parameter. The engine passes `True` when the target comes from the plan (planned kW or the idle look-ahead). Manual, surplus and keep-on-only targets keep the hold gate. Rationale: the plan is already stable across a 15-min slot; surplus is noisy. The since-last-switch gate stays for every switch — it protects hardware, and the plan rarely needs two switches within 10 minutes.

**D2 — Idle look-ahead.** A charger is idle for this purpose when it has no manual target, is not surplus-eligible, is not keep-on-only, and its planned kW for the current slot is ≤ 0.1. When idle and the next slot's planned kW for that charger is > 0.1, that next-slot kW becomes the phase target (with `skip_hold`). If the next slot also has no plan, behavior is unchanged (target 0). The balancer's charging commands are unaffected: only the phase-mode target changes, the charger stays un-commanded until its slot starts.

Next slot lookup: `_load_current_slot` already parses `schedule.json`; it will also return the slot immediately following the current one (parsed with `_parse_slot_plan`), stored on the engine for the tick. Alternative considered: a separate file read — rejected, doubles I/O and staleness checks.

**D3 — Failure grace reuses `PHASE_SWITCH_SETTLE_S` (60 s).** In `_check_ev_charge_failure`, a zero-power tick does not increment the counter when any commanded charger's `last_switch_time` is within 60 s. The counter is not reset either — it simply pauses — so a charger that was already failing before the switch still reports after the window. Chosen 60 s per user decision (observed pause ~25 s, margin for slower cars). Sharing the constant keeps "the charger is settling after a switch" one concept.

**D4 — Ramp-up hold-off after a reduction.** `LoadBalancer` records `_ev_reduced_at[charger_id]` whenever it lowers a charger's setpoint (throttle, floor degrade, relief). The ramp-up path (`Ramping …`) is refused while less than `ramp_up_window_s` has passed since that timestamp, returning the existing "Holding" output. After the hold-off the averaged window consists only of post-reduction samples, so it reflects the new house load. Reductions themselves are never delayed. The timestamp is cleared when the plan ends or the charger pauses (pause/resume already has its own anti-flap timing). Reusing `ramp_up_window_s` avoids a new setting. Scope: EV chargers only; shed-load restore already waits `resume_delay_s`.

## Risks / Trade-offs

- [Short house spike costs up to 60 s of reduced charging] → Small energy loss (≈ 1–2 A × 60 s); accepted in exchange for no sawtooth at the fuse.

- [A surplus switch shortly before a planned slot blocks the planned switch for up to 10 min] → Accepted; contactor protection wins, and the planner still sees actual power.
- [Pre-switch while the car is unplugged] → Harmless: no current flows through the contactor. Planner only plans for plugged cars anyway.
- [Plan changes after a pre-switch (replan drops the next slot)] → Next tick the target reverts to 0; the since-last-switch gate prevents flipping back within 10 min.
- [A real failure right after a switch is reported up to 60 s later] → Acceptable delay.
