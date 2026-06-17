## 1. Forecast layer config freshness

- [x] 1.1 In `backend/learning/engine.py`, record the `config.yaml` path and its last-seen mtime when loading config in `__init__`/`_load_config`.
- [x] 1.2 Add a `reload_config_if_changed()` (mtime-gated) method to `LearningEngine` that re-parses and replaces `self.config` only when the file mtime changed; reuse the cached dict otherwise.
- [x] 1.3 Add an explicit `refresh_config()` (force re-read) for use on config save.
- [x] 1.4 Call `reload_config_if_changed()` at the start of each forecast generation run (the scheduler/forward entry point that uses `get_learning_engine()`), before `ml/forward.py` reads `engine.config`.
- [x] 1.5 In `backend/api/routers/config.py` save path (alongside the existing `executor.reload_config()` at ~310-318), refresh the `LearningEngine` singleton's config.
- [x] 1.6 Audit other long-lived consumers of `engine.config` (scheduler price forecast, `ml/forward.py`) to confirm they read the refreshed reference within the same run (no in-place mutation, capture reference once per run).

## 2. DC-coupled PV generation ceiling

- [x] 2.1 In `ml/forward.py` `_pv_physical_ceiling_kwh` (~79-91), remove `max_ac_power_kw` from the ceiling computation; cap at `min(total_kwp * ceiling_efficiency, max_dc_input_kw)` (DC-side only).
- [x] 2.2 Add a log line when the ceiling is computed: effective kW value and which input bound it (panel capacity vs DC input).
- [x] 2.3 Verify the clip application sites (~440-443, 494-495, 540-541) use the updated DC-side ceiling consistently across hybrid and baseline-only modes.

## 3. Tests

- [x] 3.1 Test: editing `config.yaml` inverter limit while the engine is live → next forecast uses the new limit (mtime reload path).
- [x] 3.2 Test: unchanged config between runs → no re-parse (mtime gate holds; assert disk read not repeated).
- [x] 3.3 Test: config save via API refreshes the engine so the next forecast reads saved values.
- [x] 3.4 Test: DC-coupled config with panels/DC > AC (e.g. 14.94 kWp, 10.3 DC, 10.3 AC) → ceiling = DC-side, not reduced to AC; midday slots above AC are not flattened to the AC limit.
- [x] 3.5 Test: ceiling log line emitted with value and binding input.

## 4. Verification

- [x] 4.1 Run the existing forecast/Aurora test suites to confirm no regression in composition, monotonic quantiles, and fallback behaviour.
- [ ] 4.2 Manual: on a DC>AC config, confirm the PV forecast no longer plateaus at the AC limit and tracks a live config edit without restart.
