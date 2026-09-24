## Context

HA exposes three timestamps per state: `last_changed` (value changed), `last_updated` (value or attributes changed), `last_reported` (HA ≥ 2024.3; any report, even an identical value). The executor reads phase sensors via REST `/api/states/<id>` every tick (`executor/actions.py` `get_state`), and prod HA returns `last_reported` there (verified 2026-09-24). Today `executor/engine.py` builds `grid_current_updated_at` from `last_updated or last_changed` (power ~L2262, voltage ~L2300), so a steady but healthy sensor trips `sensor_stale_after_s`. Prod evidence: L2/L3 max gaps between value changes ≈ 31 s vs 30 s threshold.

`planner/preflight.py::check_soc_staleness` reads `initial_state.soc_timestamp`, but `backend/core/ha_client.py::get_initial_state` only fetches the SoC float (`get_ha_sensor_float`) and never sets it — the check is dead.

## Goals / Non-Goals

**Goals:**
- One shared, pure helper for "when was this live reading last reported".
- Phase power/current and voltage staleness use it.
- SoC staleness check becomes live and uses it.

**Non-Goals:**
- History-series consumers (`ml/context_features.py`, `ml/data_activator.py`, `ha_client` history/energy integration, `backend/recorder.py` meter scaling) — value-change time is semantically correct there.
- Changing `sensor_stale_after_s` default (stays 30) or the 30-min SoC threshold.
- Any WebSocket-cache path: freshness consumers all read REST state.

## Decisions

1. **Helper location: `backend/core/ha_timestamps.py`** exposing `reading_timestamp(state: Mapping) -> datetime | None` (order `last_reported` → `last_updated` → `last_changed`, skip unparseable, naive → UTC). `backend/core` is already imported by both executor and planner-input code; a leaf module with no imports avoids cycles. Alternative (keep `_parse_ha_timestamp` in engine) rejected: ha_client would need to import executor.
2. **Replace, don't wrap, `_parse_ha_timestamp`** in `executor/engine.py`: both call sites pass the whole state to the helper; the private function is removed if unused. Keeps a single source of truth.
3. **SoC: fetch full state once.** In `get_initial_state`, call `get_ha_entity_state(soc_entity_id)`, parse the value with the same rules as `get_ha_sensor_float` (factor a small `_state_float(state)` helper so behaviour/HA_UNAVAILABLE semantics are identical), and set `initial_state["soc_timestamp"] = ts.isoformat()` when available. No second HTTP call.
4. **Fallback order includes `last_changed` last** only for defensiveness; HA always sends `last_updated`, so in practice fallback = `last_updated` on pre-2024.3 HA (same behaviour as today).

## Risks / Trade-offs

- [Integration that re-reports the same value only on change (no periodic push)] → `last_reported` equals `last_updated`; behaviour identical to today, fail-safe still correct for genuinely silent sensors.
- [HA restart resets all timestamps to startup time] → readings look fresh briefly; same as today.
- [SoC warning now actually fires] → new log noise only if SoC is genuinely stale; it's a warning, planner not halted.
- [Test fixtures building states without `last_reported`] → fallback keeps them valid; add explicit new cases.

## Migration Plan

Pure code change, no config/schema migration. Deploy normally; prod temporarily runs `sensor_stale_after_s: 90` — after deploy, user may revert it to 30. Rollback = revert commit.

## Open Questions

None.
