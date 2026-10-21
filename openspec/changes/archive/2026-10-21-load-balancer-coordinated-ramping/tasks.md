## 1. Balancer core (executor/load_balancer.py)

- [x] 1.1 Add `relief_needed` trigger function wrapping the current instant threshold; route all reductions through it
- [x] 1.2 Add `PendingLedger` (grant, settle, timeout expiry, clear on reduction) with unit tests
- [x] 1.3 Add `grant_increase` shared room gate; deduct same-tick grants; visit entries in reverse give-way order
- [x] 1.4 Route EV ramp, battery ramp, plan step-up, battery resume, shed restore and 1-to-3 phase return through the gate
- [x] 1.5 Keep battery cap state when cap equals plan; plan increases ramp, decreases immediate
- [x] 1.6 Add `power_w`/`power_source` to `ShedLoadInput`; gate restore by power with worst-case fallback
- [x] 1.7 Gate shed on entries above (charger debounce)
- [x] 1.8 Per-phase fresh-sample tracking and cadence detection; one cut per sample; wait for actuator response or response timeout (2 sensor intervals, max 15 s), then cut again if still overloaded
- [x] 1.9 Battery reducible from cap and import only; response detection from measured charge
- [x] 1.10 Battery resume with escalating back-off (share EV helper) and minimum-value resume
- [x] 1.11 Battery stale-sensor fail-safe matching EV (min then pause)
- [x] 1.12 Battery W/A conversion with measured voltage and nominal fallback
- [x] 1.13 Decision-change INFO logging and `BalancerTrace` ring buffer

## 2. Engine and actuators (executor/engine.py, executor/actions.py)

- [x] 2.1 Phase reading: remove `abs()`, apply `phase_sign`, negative becomes 0 A, persistent-negative warning
- [x] 2.2 Resolve shed-load power (sensor, configured, fallback) and pass to the balancer
- [x] 2.3 Remove the balancer-triggered replan tracking and trigger; keep manual-charge and failure replans
- [x] 2.4 Write layer: adaptive per-actuator step pacing (settled or `max_step_interval_s`), deadband, `urgent` bypass for overload reductions (inverter, EV current)
- [x] 2.5 Water heater and custom switch `min_on_s`/`min_off_s` for restores and plan switching
- [x] 2.6 Expose trace snapshot accessor for diagnostics

## 3. Planner (planner/solver/kepler.py, adapter.py, pipeline.py)

- [x] 3.1 Single slot-0 duration passed to every kepler term (energy balance, surplus sink, battery limits, import/export limits, fuse row, EV supply bound, costs)
- [x] 3.2 Adapter/pipeline scale slot-0 forecast energy to remaining time; kW = kWh / remaining
- [x] 3.3 Fix `now_override` floor vs ceil
- [x] 3.4 Confirm `tests/planner/test_kepler_ev_partial_slot.py` still passes

## 4. Config and migration

- [x] 4.1 Add keys to `executor/config.py` and parsing: `max_step_interval_s`, `write_deadband_percent`, `pending_timeout_s`, `phase_sign`, loads `min_on_s`/`min_off_s`, custom `power_kw`/`power_sensor`; validation errors
- [x] 4.2 Remove `replan_after_throttled_s` from config model and parsing
- [x] 4.3 Migration dropping the key (idempotent, logged) and test
- [x] 4.4 Update `config.default.yaml` with commented defaults, remove old key
- [x] 4.5 Update docs for removed and new keys only (approved)

## 5. Frontend

- [x] 5.1 Settings fields for new global keys with help text (design system)
- [x] 5.2 Custom load row: `power_kw` and power sensor; per-load min on/off
- [x] 5.3 Remove `replan_after_throttled_s` from UI and API types

## 6. Diagnostics

- [x] 6.1 Add `balancer_trace.json` to the bundle and manifest, failure-tolerant

## 7. Tests

- [x] 7.1 Regression: plan step-up ramps (root cause 1)
- [x] 7.2 Regression: EV plus battery ramp does not overshoot with lagging average (2, 3)
- [x] 7.3 Regression: restore needs the load's power; custom worst case (4)
- [x] 7.4 Regression: shed waits for charger debounce (5)
- [x] 7.5 Regression: battery cut with lagging measured charge (6)
- [x] 7.6 Regression: no double cut on same sample (7)
- [x] 7.7 Regression: battery flap back-off and resume amount (8)
- [x] 7.8 Regression: battery stale fail-safe (9)
- [x] 7.9 Regression: adaptive pacing (fast settles early, slow waits max interval), deadband, urgent bypass, heater min off (10)
- [x] 7.10 Regression: measured voltage, sign convention (11, 12)
- [x] 7.11 Regression: no balancer replan and migration (13)
- [x] 7.12 Regression: trace buffer bound, log once, bundle includes trace (14)
- [x] 7.13 Balancer simulation: battery plus EV plus 3.1 kW heater, ten minutes, no oscillation and no sustained overload
- [x] 7.14 Planner: partial slot grid kW at most import limit, battery energy at most max charge times remaining hours, boundary plan unchanged
