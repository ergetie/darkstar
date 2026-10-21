## 1. Balancer core (executor/load_balancer.py)

- [ ] 1.1 Add `relief_needed` trigger function wrapping the current instant threshold; route all reductions through it
- [ ] 1.2 Add `PendingLedger` (grant, settle, timeout expiry, clear on reduction) with unit tests
- [ ] 1.3 Add `grant_increase` shared room gate; deduct same-tick grants; visit entries in reverse give-way order
- [ ] 1.4 Route EV ramp, battery ramp, plan step-up, battery resume, shed restore and 1-to-3 phase return through the gate
- [ ] 1.5 Keep battery cap state when cap equals plan; plan increases ramp, decreases immediate
- [ ] 1.6 Add `power_w`/`power_source` to `ShedLoadInput`; gate restore by power with worst-case fallback
- [ ] 1.7 Gate shed on entries above (charger debounce)
- [ ] 1.8 Per-phase fresh-sample tracking and cadence detection; one cut per sample; wait for actuator response or response timeout (2 sensor intervals, max 15 s), then cut again if still overloaded
- [ ] 1.9 Battery reducible from cap and import only; response detection from measured charge
- [ ] 1.10 Battery resume with escalating back-off (share EV helper) and minimum-value resume
- [ ] 1.11 Battery stale-sensor fail-safe matching EV (min then pause)
- [ ] 1.12 Battery W/A conversion with measured voltage and nominal fallback
- [ ] 1.13 Decision-change INFO logging and `BalancerTrace` ring buffer

## 2. Engine and actuators (executor/engine.py, executor/actions.py)

- [ ] 2.1 Phase reading: remove `abs()`, apply `phase_sign`, negative becomes 0 A, persistent-negative warning
- [ ] 2.2 Resolve shed-load power (sensor, configured, fallback) and pass to the balancer
- [ ] 2.3 Remove the balancer-triggered replan tracking and trigger; keep manual-charge and failure replans
- [ ] 2.4 Write layer: adaptive per-actuator step pacing (settled or `max_step_interval_s`), deadband, `urgent` bypass for overload reductions (inverter, EV current)
- [ ] 2.5 Water heater and custom switch `min_on_s`/`min_off_s` for restores and plan switching
- [ ] 2.6 Expose trace snapshot accessor for diagnostics

## 3. Planner (planner/solver/kepler.py, adapter.py, pipeline.py)

- [ ] 3.1 Single slot-0 duration passed to every kepler term (energy balance, surplus sink, battery limits, import/export limits, fuse row, EV supply bound, costs)
- [ ] 3.2 Adapter/pipeline scale slot-0 forecast energy to remaining time; kW = kWh / remaining
- [ ] 3.3 Fix `now_override` floor vs ceil
- [ ] 3.4 Confirm `tests/planner/test_kepler_ev_partial_slot.py` still passes

## 4. Config and migration

- [ ] 4.1 Add keys to `executor/config.py` and parsing: `max_step_interval_s`, `write_deadband_percent`, `pending_timeout_s`, `phase_sign`, loads `min_on_s`/`min_off_s`, custom `power_kw`/`power_sensor`; validation errors
- [ ] 4.2 Remove `replan_after_throttled_s` from config model and parsing
- [ ] 4.3 Migration dropping the key (idempotent, logged) and test
- [ ] 4.4 Update `config.default.yaml` with commented defaults, remove old key
- [ ] 4.5 Update docs for removed and new keys only (approved)

## 5. Frontend

- [ ] 5.1 Settings fields for new global keys with help text (design system)
- [ ] 5.2 Custom load row: `power_kw` and power sensor; per-load min on/off
- [ ] 5.3 Remove `replan_after_throttled_s` from UI and API types

## 6. Diagnostics

- [ ] 6.1 Add `balancer_trace.json` to the bundle and manifest, failure-tolerant

## 7. Tests

- [ ] 7.1 Regression: plan step-up ramps (root cause 1)
- [ ] 7.2 Regression: EV plus battery ramp does not overshoot with lagging average (2, 3)
- [ ] 7.3 Regression: restore needs the load's power; custom worst case (4)
- [ ] 7.4 Regression: shed waits for charger debounce (5)
- [ ] 7.5 Regression: battery cut with lagging measured charge (6)
- [ ] 7.6 Regression: no double cut on same sample (7)
- [ ] 7.7 Regression: battery flap back-off and resume amount (8)
- [ ] 7.8 Regression: battery stale fail-safe (9)
- [ ] 7.9 Regression: adaptive pacing (fast settles early, slow waits max interval), deadband, urgent bypass, heater min off (10)
- [ ] 7.10 Regression: measured voltage, sign convention (11, 12)
- [ ] 7.11 Regression: no balancer replan and migration (13)
- [ ] 7.12 Regression: trace buffer bound, log once, bundle includes trace (14)
- [ ] 7.13 Balancer simulation: battery plus EV plus 3.1 kW heater, ten minutes, no oscillation and no sustained overload
- [ ] 7.14 Planner: partial slot grid kW at most import limit, battery energy at most max charge times remaining hours, boundary plan unchanged
