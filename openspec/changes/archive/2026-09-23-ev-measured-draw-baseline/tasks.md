## 1. Measured draw

- [x] 1.1 `EVChargerState`: add `measured_draw_a: float | None` and `setpoint_changed_at: datetime | None`. Set `setpoint_changed_at` wherever `current_setpoint_a` changes value (actuation success paths), and clear it on stop.
- [x] 1.2 Add `_update_ev_measured_draw(charger_cfg, dev_state, phase_ctrl)` in `executor/engine.py`: per-phase sensors (max; A as is, W/kW ÷ 230) → disaggregator power for that charger id when `is_healthy` (`power_w / (230 × _resolve_active_phase_count)`) → `None`. Treat the EV power fail-safe (`_ev_power_fetch_failed`) as no measurement.
- [x] 1.3 Call it for every current-type charger at the start of `_update_ev_surplus_and_phase_mode`, before any controller runs. Fold the per-phase sensor read into it so `active_phases` detection reuses the same readings, and remove the second read in `_control_ev_charger`.
- [x] 1.4 Add `_effective_baseline_a(charger_cfg, dev_state, now)` with the `EV_DRAW_SETTLE_S = 30` module constant, following the design's formula.

## 2. Controllers

- [x] 2.1 `EVSurplusController.tick`: new `baseline_a` argument, used for `desired = baseline + delta` and the ramp step. The engine passes the effective baseline.
- [x] 2.2 `EVBalancerInput.effective_draw_a` (defaults to `current_setpoint_a`). `_resolve_ev` reduces and holds from it, and the pool fold uses it as `previous_draw`. The engine populates it in `_run_load_balancer`.

## 3. Status

- [x] 3.1 Add `measured_a` to each charger entry in the balancer status payload (REST + live-metrics WebSocket).
- [x] 3.2 Load-balancer status row in the frontend: show "drawing X A" when `measured_a` is present, using design-system tokens. Update the API types.

## 4. Tests

- [x] 4.1 Measured draw: total-power path (6900 W, 3-phase → 10 A), per-phase precedence, unavailable → `None`, fail-safe → `None`.
- [x] 4.2 Effective baseline: car below setpoint, inside settle window, measurement above setpoint, no measurement, below floor clamps to `min_current_a`.
- [x] 4.3 Surplus: settled 16 A, 10 A draw, 2.07 kW import → 7 A. Without a measurement the existing results are unchanged.
- [x] 4.4 Balancer: 16 A setpoint, 10 A draw, −4 A headroom → ≤ 6 A, and a later entry sees relief computed from 10 A. Existing balancer tests pass unchanged (default = setpoint).
- [x] 4.5 Status payload and frontend row render `measured_a`.

## 5. Verification

- [x] 5.1 Run `./scripts/lint.sh` and the full test suite.

Post-deployment (not part of this change's completion): on production, watch a surplus session in the load-balancer status and confirm the measured draw is shown and that reductions land below it.
