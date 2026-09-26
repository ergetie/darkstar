## Why

On prod (2026-09-25) a 16 A main fuse with the Go-e charging at 12 A per phase paused charging four times in one afternoon. The balancer computed the numbers correctly, but it has only two responses: lower the amps, or pause once the setpoint would fall below 6 A. A single one-second spike on one phase (L3 hit ~23.5 A) is enough to stop the whole session. It never uses 1-phase mode to move off the overloaded phase. It aims at 100 % of the fuse rather than keeping a safety margin. It also sends a push notification for every pause. The result is noisy, fragile charging that delivers less than planned.

## What Changes

- **Target safety margin.** The balancer steers each phase toward `target_margin_percent` of `main_fuse_a` (new, default 85 %, user-configurable) instead of toward 100 %. Dropping below the fuse is still an instant hard reaction; the target only governs how high it ramps.
- **Degradation ladder.** On overload a phase-switching-capable charger degrades in this order:
  1. Reduce amps instantly.
  2. If at `min_current_a` and still overloaded on a phase the 1-phase line does not use, command 1-phase mode.
  3. Pause.
  Chargers without phase switching skip step 2.
- **Pause debounce.** A charger at its floor pauses only if the overload persists for `pause_debounce_s` (new, default 5 s, user-configurable). An overload above `severe_overload_percent` of the fuse (new, default 125 %) pauses immediately.
- **Quick re-fit while paused.** A paused charger resumes once its phases have fitted the minimum current within the target margin for `resume_confirm_s` (new, default 10 s), in its current mode or, if dwell allows, 1-phase on `phase_1_line`, at the largest current that fits up to the plan. Repeated pauses lengthen the wait (30 s, 120 s; reset after 10 min). `resume_delay_s` no longer gates this resume.
- **Asymmetric sensing.**
  - Decreases, the ladder descent and the severe-overload check use the momentary reading.
  - Increases, resume, and the return from 1-phase to 3-phase use a rolling average over `ramp_up_window_s` (new, default 60 s).
  - The existing `phase_switch_min_dwell_s` (default 600 s) still bounds every phase change.
- **Balancer owns phase mode under overload.** Phase switching today is driven only by surplus, manual and plan target power (`executor/engine.py` `_update_ev_surplus_and_phase_mode`). The balancer becomes a second input that can demand 1-phase for relief. The state machine, dwell and fail-safe stay unchanged.
- **Configurable 1-phase line.** A per-charger `phase_1_line` (new, default `1`) declares which grid phase the charger uses in 1-phase mode, so the balancer knows which phases 1-phase relieves.
- **Notifications.**
  - Pause notifications are sent only when the pause puts an active EV goal at risk.
  - Other pauses are recorded in the execution log only. There is no daily summary.
  - Shed and stale-sensor notifications are unchanged.
- **Phase-mode picker.** The phase-mode entity picker offers only writable `select.*` / `input_select.*` entities, so read-only sensors such as `binary_sensor.*_fsp` can no longer be chosen. The existing option dropdown for the 1-/3-phase values stays.
- The IEC 61851 6 A minimum stays the hard per-phase floor; nothing charges below `min_current_a`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `phase-load-balancing`: target margin; degradation ladder including 1-phase relief; debounced and severe-overload pause; averaged ramp-up/resume; goal-at-risk pause notifications.
- `ev-phase-switching`: the balancer can demand 1-phase for overload relief; a configurable `phase_1_line`; returning to 3-phase requires averaged headroom.
- `load-balancing-settings`: new settings (`target_margin_percent`, `pause_debounce_s`, `resume_confirm_s`, `severe_overload_percent`, `ramp_up_window_s`, per-charger `phase_1_line`) in schema, validation and UI; the phase-mode picker filtered to writable select domains.

## Impact

- `executor/load_balancer.py`: margin target, ladder, debounce, severe check, averaged ramp-up.
- `executor/engine.py`: phase-mode decision gets the balancer's relief request; per-phase rolling-average buffer; notification gating.
- `executor/ev_surplus.py` (`PhaseModeController`): accepts a forced-1-phase relief demand; still subject to dwell and fail-safe.
- `executor/config.py`, `config.default.yaml`, `backend/api/routers/config.py`: new keys, defaults and validation.
- `frontend/src/pages/settings/components/EntityArrayEditor.tsx`, `frontend/src/pages/settings/types.ts`: new fields and domain-filtered picker.
- Notifications: the existing HA-notify / Discord path; reads the goal-at-risk signal from the planner's `ev_goal_diagnostics`.
- No DB schema change. No new dependencies.
