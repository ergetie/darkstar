## Why

Real logs and a real-solver harness (investigation 2026-10-21) show the load balancer and the planner cause the overloads they should prevent. Battery plan step-ups bypass the ramp/room gate (3000 to 6000 W in one write, import above 12 kW). EV (+1 A per tick) and battery (+600 W per tick) ramp together against a lagging 60 s average and overshoot (import 4.3 to 10.7 kW in 30 s). A shed heater is restored as if it drew 0 A, so a 3.1 kW heater cycles every ~125 s while the battery is starved. The battery cut is skipped while measured charge lags the cap, repeated cuts act on the same phase sample, and battery pause/resume flaps 8 times in 4 minutes. The planner treats a partially elapsed slot 0 as a full slot for everything except EV energy, so with 4 minutes left it plans a 6 kW battery charge that really draws about 16.9 kW against an 11 kW limit. A balancer-triggered replan passes no fuse information and cannot help.

## What Changes

- Cross-tick pending-increase ledger and one shared room gate for all increase paths (EV, battery, shed, custom, plan step-ups, resume, restore). Battery plan increases ramp, never jump.
- Shed-load restore is gated by the load's power (live sensor, then configured power, then worst-case full fuse). New optional `power_kw` and `power_sensor` for custom loads.
- Shed respects the entries above it (pause debounce).
- Act once per fresh phase sample (detected cadence); wait for actuator response (timeout two sensor intervals, at most 15 s) before cutting again.
- Battery cut works while measured charge lags the cap; battery resume uses escalating back-off and a target margin; battery stale-sensor fail-safe matches the EV (min, then pause).
- Anti-wear: adaptive step pacing (next step after the previous settled, at most 30 s), deadband, water heater and custom switch `min_on_s`/`min_off_s` (default 300 s). Overload reductions stay immediate.
- Measured voltage for battery W/A conversion with nominal fallback; no `abs()` on phase readings (new `phase_sign`, negative becomes 0 A).
- **BREAKING (silent, migrated)**: remove the balancer-triggered replan and `load_balancing.replan_after_throttled_s` (config migration, default template, settings UI, docs).
- Planner: one remaining-time basis for every slot-0 flow, limit, cost and kW conversion.
- Observability: decision-change log lines, bounded ring-buffer trace, `balancer_trace.json` in the diagnostics bundle.
- Reduction triggering is isolated behind one pluggable function so the separate `fuse-overload-timing` change (proportional overload timing) can replace it.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `phase-load-balancing`: ledger, shared room gate, restore power, fresh-sample rule, battery cut/resume/stale, anti-wear, voltage, sign, observability; removes the sustained-battery replan.
- `load-balancing-settings`: new keys, custom load power fields, UI.
- `planner`: slot-0 remaining-time basis.
- `ev-target-charging`: partial-slot requirement extended to all flows.
- `ev-charging-replan`: removes the sustained-balancer-throttling replan.
- `ev-charge-failure-detection`: drops the balancer rate-limit coupling.
- `diagnostics-export`: adds `balancer_trace.json`.
- `config-migration`: drops `replan_after_throttled_s`.

## Impact

- Backend: `executor/load_balancer.py`, `executor/engine.py` (balancer wiring, phase reading, replan removal, trace), `executor/actions.py` (write throttling), `executor/config.py` (new keys, custom power fields, parsing), config migration module, `planner/solver/kepler.py`, `planner/solver/adapter.py`, `planner/pipeline.py`, diagnostics export router.
- Frontend: load balancing settings tab, custom load row, status card unchanged except reasons.
- Config: `config.default.yaml`, docs under `docs/` (ask first; user-facing text only for the removed key and new keys).
- Tests: regression test per root cause, balancer simulation, planner partial-slot tests; `tests/planner/test_kepler_ev_partial_slot.py` stays valid.
- Not touched: BACKLOG item "[Load Balancer] Proportional Overload Timing" (separate change `fuse-overload-timing`). "[Planner] Per-Phase Load Awareness" stays in the backlog, only partly covered here.
