## Why

The forecast layer runs on a config snapshot frozen at process startup. `LearningEngine` is a process-wide singleton (`backend/learning/__init__.py`) that loads `config.yaml` once in its constructor and is never reset or reloaded — not even when config is saved through the UI (only the executor reloads on save). Meanwhile the planner/executor read fresh config each tick. The result is a split-brain: the planner uses current config while every forecast (load, PV, price, solar-array geometry, weather location) uses stale startup config.

This surfaced as a beta tester's PV forecast being clipped to a perfectly flat plateau at a kW level that does not match his current config (his app shows inverter AC/DC = 10.3 kW, but the forecast clips lower). After migrating his data and editing config, the running engine kept clipping at the inverter limit that was present at startup. A separate but related defect: even with correct config, the PV physical ceiling clips PV *generation* at the AC inverter limit, which is wrong for DC-coupled battery systems where surplus PV charges the battery on the DC side above the AC limit.

## What Changes

- The forecast layer SHALL reflect the current on-disk config instead of a startup snapshot: detect `config.yaml` mtime changes and re-parse, so load/PV/price forecasts and solar-array/weather inputs always use current values.
- Config saved through the API SHALL propagate to the forecast layer (the `LearningEngine` singleton), not only the executor.
- The PV physical ceiling SHALL NOT clip PV generation at the inverter AC limit for DC-coupled systems; the generation ceiling SHALL be based on DC input and panel capacity. **BREAKING** for the current clipping behavior (PV forecasts will read higher midday on oversized-array systems).
- Add observability: log the effective PV ceiling (value and which limit bound it) when generating forecasts, so a stale or wrong ceiling is diagnosable from logs.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `config-caching`: Extend config-freshness guarantees to the forecast layer. The `LearningEngine` (and anything reading its `config`) SHALL pick up config changes via mtime detection / reload, so forecasts never run on a stale startup snapshot. Config save SHALL invalidate/refresh the engine's cached config.
- `physics-based-pv-forecasting`: The "Final Forecast Composition" physical ceiling SHALL use DC input / panel-capacity limits for generation and SHALL NOT clip generation at the AC inverter limit on DC-coupled systems. The effective ceiling SHALL be logged.

## Impact

- Code:
  - `backend/learning/__init__.py` (`get_learning_engine` singleton), `backend/learning/engine.py` (`_load_config`, config storage) — add mtime-aware reload / refresh hook.
  - `backend/api/routers/config.py` (config save path) — notify/refresh the engine like it already does for the executor.
  - `ml/forward.py` (`_pv_physical_ceiling_kwh`, lines ~79-91, 440-443, 540-541) — DC-coupled ceiling logic + ceiling logging.
- Behavior: PV forecasts on oversized-array (DC > AC) systems will no longer plateau at the AC limit; load/price forecasts and solar-array geometry will track live config without a restart.
- Risk: re-reading config mid-process must stay cheap (mtime-gated) to avoid per-forecast disk I/O; concurrent access to the engine config must remain safe.
