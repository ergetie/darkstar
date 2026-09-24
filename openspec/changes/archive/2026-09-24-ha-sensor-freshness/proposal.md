## Why

The load balancer judges phase-sensor freshness from HA's `last_updated`, which only moves when the value or attributes change. A healthy sensor that reports the same reading twice (observed on prod: L2/L3 gaps of ~31 s against a 30 s threshold) looks stale, so the fail-safe falsely forces the EV to 6 A and notifies the user. Separately, the planner's SoC staleness pre-flight check never runs because nothing populates `initial_state.soc_timestamp`.

## What Changes

- Freshness of an HA reading SHALL be judged from `last_reported` (HA ≥ 2024.3: bumped on every report, even unchanged values), falling back to `last_updated`, then `last_changed`, when absent.
- One shared helper extracts this "reading freshness" timestamp; the load balancer's phase power/current and phase voltage readings use it.
- `get_initial_state` SHALL populate `soc_timestamp` from the SoC entity's freshness timestamp so the existing 30-minute `DATA_STALE` warning actually fires (and does not false-fire on a steady SoC, e.g. a full battery).
- Default `sensor_stale_after_s` stays 30 s.
- Out of scope (deliberately unchanged): history-based ML/import code and the energy recorder's time-proportional scaling, which correctly use change time.

## Capabilities

### New Capabilities
- `ha-reading-freshness`: how Darkstar determines the age of a live HA sensor reading (`last_reported` → `last_updated` → `last_changed`).

### Modified Capabilities
- `phase-load-balancing`: stale-sensor fail-safe measures age from the reading-freshness timestamp, not last value change.
- `planner`: the SoC staleness pre-flight check is fed a real timestamp from the SoC entity.

## Impact

- `executor/engine.py` (phase power + voltage timestamp extraction, `_parse_ha_timestamp`)
- `backend/core/ha_client.py` (`get_initial_state` SoC read now needs the full state)
- `planner/preflight.py` (consumer; behaviour unchanged, now reachable)
- New shared helper module + tests; no config, schema, API or dependency changes.
