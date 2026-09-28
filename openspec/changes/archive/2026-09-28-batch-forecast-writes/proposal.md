## Why

After the Open-Meteo mapping fix, a prod planner run takes ~12 s, of which ~6.4 s is avoidable per-row overhead. Measured on prod hardware 2026-09-28 (DB writes against a copy of the prod DB): saving 672 forecast rows one statement at a time takes 4.5-4.9 s versus ~40 ms batched with identical rows; saving the plan takes ~470 ms versus 13 ms; the per-slot sun-up check recomputes sunrise/sunset 2,016 times (0.71 s vs 45 ms cached, identical); the hybrid PV clamp loop runs row by row (0.60 s). Every install runs these on every planner run.

## What Changes

- `store_forecasts`: one batched (executemany) upsert per call instead of one statement per row. Same conflict target and update rules, including keeping an existing `openmeteo_pv_forecast_kwh` when the new value is NULL.
- `store_plan`: same batching, same upsert rules (`created_at` refreshed on update).
- `SunCalculator`: cache sunrise/sunset per calendar date; `is_sun_up` results unchanged.
- Hybrid PV inference in `ml/forward.py`: compute residual bounding, astro clamp, radiation clamp, floor and ceiling over the whole horizon at once instead of per row. Values unchanged.
- No API, config, or schema changes.

## Capabilities

### New Capabilities

- `planner-run-performance`: per-run write and compute paths scale with batch operations, not per-row statements or repeated astronomical calculations, with results identical to the previous behaviour.

### Modified Capabilities

_None._

## Impact

- `backend/learning/store.py` (`store_forecasts`, `store_plan`)
- `backend/astro.py` (`SunCalculator`)
- `ml/forward.py` (hybrid PV loop)
- Tests: `tests/ml/test_learning_engine.py`, `tests/ml/test_store_plan_mapping.py`, `tests/planner/test_astro.py`, `tests/ml/test_hybrid_pv_integration.py`, `tests/ml/test_aurora_forward.py`
- Expected: prod planner run ~12 s → ~5.5 s; installs on default `horizon_days: 2` save ~1.4 s less on the forecast write (192 rows).
