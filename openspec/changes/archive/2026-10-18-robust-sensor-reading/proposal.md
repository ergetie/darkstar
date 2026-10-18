# Proposal

## Why

With a water heater using `control_type: switch`, the executor reads the heater's `target_entity` (a switch, state "on"/"off") as a temperature. `float("on")` raises inside the single try/except of `_gather_system_state` (executor/engine.py), which aborts the rest of the gather. The phase-current block never runs, `grid_current_a` stays None, the load balancer treats every phase as stale and pauses EV charging indefinitely (reported by user torleif). The stale message is also misleading ("Phase sensor(s) [3] stale for 332489s": [3] is the binding phase list, and the duration is time since the first stale tick, not sensor age).

## What Changes

- Skip the `water_temp` read for water heaters with `control_type: switch`; keep it for `temperature`.
- Isolate each sensor read/parse so one bad sensor cannot block others; the phase-current block runs independently.
- Replace the blanket "Failed to gather some system state" warning with a rate-limited per-entity warning (entity id + reason).
- Load balancer stale messages name the stale phase sensors and report real reading age, separately from the time spent stale.
- Add regression tests for the torleif case.

## Capabilities

### New Capabilities

### Modified Capabilities
- `executor`: system-state gathering must tolerate per-sensor failures and not read non-numeric entities as numbers.
- `phase-load-balancing`: stale-sensor status messages identify sensors and real age.

## Impact

- executor/engine.py (`_gather_system_state`), executor/load_balancer.py (`_is_stale`, `_resolve_ev` messages).
- tests under tests/executor/ (engine gather, load balancer).
- No config, schema, API or dependency changes.
