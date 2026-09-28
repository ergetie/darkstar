## 1. Reference tests (against current code)

- [x] 1.1 `store_forecasts` tests: insert 672 rows, update existing rows, NULL `openmeteo_pv_forecast_kwh` keeps stored value, row without slot start skipped, duplicate slot last-wins
- [x] 1.2 `store_plan` tests: derived energies scaled by slot duration, missing end stored NULL with warning, `created_at` refreshed on update
- [x] 1.3 `SunCalculator` test: 7 days x 96 slots with 30-minute buffer, capture results as reference
- [x] 1.4 Hybrid PV test: fixed 672-slot fixture, capture per-slot reference output from the current loop (keep the reference implementation in the test)
- [x] 1.5 Run all new tests against current code; all pass

## 2. Implementation

- [x] 2.1 `backend/learning/store.py` `store_forecasts`: build row dicts, then one `session.execute(upsert_stmt, rows)`
- [x] 2.2 `backend/learning/store.py` `store_plan`: same batching, keep per-slot warning and duration scaling
- [x] 2.3 `backend/astro.py`: per-date sun-time cache on the instance (cache `None` results too)
- [x] 2.4 `ml/forward.py` hybrid PV: vectorised residual bound, weighting, astro/radiation clamps, floor, ceiling; sun-up flags computed once and shared across quantiles; `_pv_tuning_config` read once
- [x] 2.5 Add a call-count assertion that the astronomical calculation runs once per date
- [x] 2.6 Hybrid PV NaN handling: bound and floor with builtin `min`/`max` semantics so NaN residuals and NaN values give the same results as the per-slot loop; NaN reference tests

## 3. Verification

- [x] 3.1 Run the new tests plus `tests/ml/test_learning_engine.py`, `tests/ml/test_store_plan_mapping.py`, `tests/planner/test_astro.py`, `tests/ml/test_hybrid_pv_integration.py`, `tests/ml/test_aurora_forward.py`
- [x] 3.2 Benchmark the real methods on a local synthetic SQLite DB and confirm `store_forecasts` < 0.1 s and `store_plan` < 0.05 s (measured: 672 forecast rows ≈6 ms, 100 plan rows ≈3 ms; a prod benchmark follows after deploy, outside this change)
- [x] 3.3 Run `./scripts/lint.sh`
