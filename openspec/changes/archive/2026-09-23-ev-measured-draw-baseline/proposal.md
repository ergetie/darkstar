## Why

Surplus charging and the load balancer adjust a current-type charger's amps starting from the last *commanded* setpoint. The setpoint is only a ceiling: the car often draws less (taper near full, onboard limits, ramp-up). When that happens, reductions land above the actual draw and change nothing. With a 16 A setpoint and a car drawing 10 A, a cloud that causes 2 kW import lowers the setpoint to about 13 A, the draw stays at 10 A, and the house keeps importing for several ticks. The balancer's in-tick relief estimate is inflated in the same way.

## What Changes

- The executor derives each current-type charger's **measured draw per phase (A)** every tick. It uses the charger's per-phase sensors when configured, otherwise the charger's existing total power `sensor` divided by `230 V × active phases`.
- Surplus feedback uses an **effective baseline** = `min(commanded setpoint, measured draw)` (never below `min_current_a`) instead of the commanded setpoint, once the draw has settled after the last setpoint change.
- The load balancer uses the same effective baseline when it reduces or holds a charging EV, and when it folds that charger's relief into the shared headroom pool.
- When no fresh measurement exists (sensor unavailable, not configured, not yet settled), behaviour is exactly as today (commanded setpoint).
- The balancer status per charger shows measured draw next to setpoint and planned target.

## Capabilities

### New Capabilities
- `ev-measured-draw`: per-tick measured EV draw per phase, source selection, settle window and fallback rules.

### Modified Capabilities
- `ev-surplus-charging`: feedback adjusts from the effective baseline rather than the commanded setpoint.
- `phase-load-balancing`: reduction, hold and relief accounting for a charging EV use the effective baseline.
- `load-balancing-settings`: live status per charger includes measured draw.

## Impact

- `executor/engine.py`: measurement step before surplus/balancer, `EVChargerState` fields (`measured_draw_a`, `setpoint_changed_at`), inputs to `EVSurplusController.tick` and `EVBalancerInput`.
- `executor/ev_surplus.py`, `executor/load_balancer.py`: take an effective baseline input.
- Balancer status payload + `frontend` load-balancer status row.
- No config change, no new dependency, no DB change. Production go-e already has `sensor: sensor.go_echarger_417263_power_total`; its per-phase sensors are empty, so the total-power fallback is the path that will run there.
