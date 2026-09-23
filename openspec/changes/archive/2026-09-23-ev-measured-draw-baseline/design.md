## Context

- Tick order (`executor/engine.py`): EV power read via the load disaggregator (`update_current_power`, ~line 1424) → surplus + phase mode (`_update_ev_surplus_and_phase_mode`, ~1548) → load balancer (`_run_load_balancer`, ~1560) → actuation (`_control_ev_charger`, ~1614).
- Both controllers take `dev_state.current_setpoint_a`, which is the last commanded amps value. Since `fix-ev-current-charger-control`, the dispatcher writes it back to HA every tick, so it equals the charger's amps setting. It is not the car's draw.
- `EVSurplusController.tick` (`executor/ev_surplus.py`): `baseline_a = current_setpoint_a`, `desired = baseline + delta(surplus)`.
- `LoadBalancer._resolve_ev` (`executor/load_balancer.py`) reduces or holds from `ev.current_setpoint_a`, and the pool fold uses `previous_draw = entry.current_setpoint_a`.
- Per-charger power is already read every tick: `DeferrableLoad.current_power_kw` / `is_healthy`, keyed by charger id, sourced from `ev_chargers[].sensor` and normalised W/kW.
- Per-phase sensors `phase_sensor_l1..l3` are optional and are only read inside actuation (`_update_ev_active_phases`), which runs after the controllers.
- Production go-e: `sensor: sensor.go_echarger_417263_power_total`, per-phase sensors empty, 3 phases, 6–16 A.

## Goals / Non-Goals

**Goals:**
- Reductions (surplus import, fuse deficit) act on what the car actually draws.
- Behaviour is unchanged whenever no trustworthy measurement exists.
- Measured draw is visible in the balancer status.

**Non-Goals:**
- Headroom computation. It already uses measured grid phase currents.
- Planner-side changes, or any config/schema change.
- Detecting a car that refuses to charge at all. That is covered by `ev-charge-failure-detection`.

## Decisions

1. **Measured draw per phase (A), computed once per tick, before the controllers.**
   - Source order:
     1. Per-phase sensors, if any are configured and readable. The draw is the maximum across the charger's phases. W/kW readings are converted with 230 V; A readings are used as is.
     2. The charger's total power reading from the disaggregator, when `is_healthy`: `power_w / (230 × active_phase_count)`, using the same active phase count the controllers use (`_resolve_active_phase_count`).
     3. Otherwise `None`.
   - Stored as `EVChargerState.measured_draw_a`.
   - The per-phase sensor read moves ahead of the surplus step, so it happens once per tick rather than twice; `active_phases` detection reuses the same readings.
   - Why max per phase: the balancer and the setpoint both work per phase, and the binding phase is the highest one.
   - Alternative rejected: reading the charger's own amps entity. It equals our setpoint, not the car's draw.

2. **Effective baseline.**
   - `effective = max(min_current_a, min(setpoint, measured))` when all of the following hold:
     - a setpoint exists,
     - `measured` is not `None`,
     - the setpoint has been unchanged for at least `EV_DRAW_SETTLE_S = 30` s (`EVChargerState.setpoint_changed_at`).
   - Otherwise `effective = setpoint`.
   - `min(...)`: a measurement above the setpoint (sensor noise, rounding) must never raise the baseline.
   - `max(min_current_a, ...)`: a car drawing below the floor is treated as being at the floor. A further reduction then goes below the floor and triggers the existing pause path, instead of computing a nonsense sub-floor baseline.
   - Settle window: the car needs seconds to follow a new setpoint. Without the window, the tick after a start would read ~0 A and pause the charger. The 30 s value is a module constant, matching the existing `_EV_PHASE_ACTIVE_THRESHOLD_*` style. It is not user config.

3. **Surplus controller.** `tick()` gets a new `baseline_a` argument (the effective baseline), used in place of `current_setpoint_a` for `desired = baseline + delta` and for the ramp step. `current_setpoint_a is None` keeps its meaning of "not charging". The increase ramp therefore counts from the real draw, so a car-limited EV no longer drags the setpoint up to max.

4. **Load balancer.**
   - `EVBalancerInput` gets `effective_draw_a`, defaulting to `current_setpoint_a`.
   - `_resolve_ev` reduces or holds from it.
   - The pool fold uses `previous_draw = effective_draw_a`.
   - The raise path and the planner ceiling are unchanged.
   - With the default, balancer output is identical when no measurement exists, so existing tests keep passing.

5. **Status.** Each charger entry in the balancer status gets `measured_a` (or `null`). The UI row shows "drawing X A" next to setpoint/planned when present.

## Risks / Trade-offs

- [Power-derived amps are off when the car uses fewer phases than assumed] → `active_phase_count` already comes from measurement or the commanded phase mode. Worst case the baseline is too high, which means today's behaviour.
- [Sensor lag makes the measurement stale] → The settle window plus `min(setpoint, …)` means stale readings can only lower the baseline toward what the car drew recently. A reduction then undershoots slightly, and the increase ramp recovers it. No grid-import risk.
- [Oscillation at the car's own limit: setpoint trails at measured + step] → Bounded by one ramp step and harmless, because the car caps itself.
- [230 V constant vs real voltage] → ±5 % error in amps. Acceptable for a baseline, and consistent with `planned_kw_to_amps`.

## Migration Plan

No config or data migration. Rollback = revert.
