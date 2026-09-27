## Why

On 2026-09-27 the planner scheduled 6.9 kW EV charging from 11:50:50, but the charger stayed on 1-phase (~2.3 kW) until 12:00:50 because the phase controller waits the full 600 s dwell before acting on any target change — a guard designed for fluctuating solar surplus, not for a known plan. The switch then paused the go-e for ~25 s, which the charge-failure check (5 zero-power ticks) reported as a failure and answered with an unnecessary replan.

## What Changes

- Planned (schedule-driven) EV targets switch phase mode at the slot boundary instead of waiting for the target to hold for `min_dwell_s`. Surplus-driven targets keep the existing hold window.
- While a charger is idle, the executor looks one slot ahead and pre-switches to the phase mode the next planned slot needs, so the charger's switch-over pause happens while nothing is charging.
- The minimum time between two phase switches (`min_dwell_s`, contactor protection) still applies to every switch.
- After the load balancer reduces a charger's setpoint, it does not raise that charger again for `ramp_up_window_s` (60 s). Today the 60 s average still holds pre-spike samples right after a new house load starts, so the balancer climbs straight back to the fuse limit and gets cut again (observed 12:39–12:40 on 2026-09-27: 8→6→7→8→7→6 A).
- EV charge-failure detection ignores zero-power ticks for 60 s after a commanded phase switch, so the charger's own switch-over pause no longer raises a failure notification or replan.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `ev-phase-switching`: planned targets bypass the target-hold window; new idle look-ahead pre-switch requirement.
- `ev-charge-failure-detection`: 60 s grace after a commanded phase switch.
- `phase-load-balancing`: ramp-up hold-off after a setpoint reduction.

## Impact

- `executor/ev_surplus.py` — `PhaseModeController.decide()` gains a way to skip the target-hold window.
- `executor/engine.py` — `_update_ev_surplus_and_phase_mode()` (target source, idle look-ahead), schedule loading (next slot), `_check_ev_charge_failure` (grace window).
- `executor/load_balancer.py` — per-charger last-reduction timestamp gating the ramp-up path.
- Tests in `tests/` for phase controller, engine phase-mode flow and failure detection.
- No config, API, DB or frontend changes.
