# Tasks

## 1. Forecast slot boundary (Item A)

- [x] 1.1 In `ml/price_features.py` pass `inclusive="left"` to the `dst_safe_date_range` call in `build_price_features_batch`. Verify: new test shows 96, 92 (2026-03-29) and 100 (2026-10-25) slots with last slot 23:45 local.
- [x] 1.2 Add optional local-date bounds and an optional `days_ahead` to the selection in `get_price_forecasts_from_db` (`ml/price_forecast.py`). Verify: unit test with rows on three dates returns only the requested date.
- [x] 1.3 Change `get_d1_price_forecast_fallback` to select tomorrow's local-date slots from the latest issue per slot across all `days_ahead` values (valid `spot_p50`, one row per `slot_start`, no row limit, stale filter `slot_date == tomorrow`) and add `forecast_days_ahead` to each record. Verify: tests for before the daily issue (only yesterday's issue, `forecast_days_ahead=2`, all slots incl. 00:00), after the issue (`forecast_days_ahead=1`), mixed issues (latest per slot), old overlapping rows (00:00 once), and the 100-slot fall-back day.
- [x] 1.3a In `backend/core/prices.py` carry `forecast_days_ahead` through fallback entries and `_process_nordpool_data` into the price data, keeping `price_source: "forecast"`. Verify: test that `get_nordpool_data` output for fallback slots has both keys and published slots have no `forecast_days_ahead`.
- [x] 1.4 Test that `get_nordpool_data` merged with the fallback is continuous at 15 minutes across midnight, and that persisted forecasts have no duplicate `slot_start` across `days_ahead`. Verify: tests pass.
- [x] 1.5 Grep tests for 97-row or inclusive-end assertions and update them. Confirm `ml/forward.py` and `ml/context_features.py` are unchanged and `backend/core/price_outlook.py` needs no change (dict-keyed slots). Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/ml tests/utils -q` passes.

## 2. Battery benchmark relaxation (Item B)

- [x] 2.1 Extend `KeplerBenchmark` in `planner/solver/types.py` with optional per-slot relaxation (import, export, inverter AC kWh caps, export-limits-off flags) and apply it in `planner/solver/kepler.py` benchmark branch only. Verify: `test_live_kepler_does_not_use_benchmark_mode` still passes and a solver-level test shows an over-limit recorded slot becomes feasible.
- [x] 2.2 In `backend/battery_benchmark.py` build the relaxation from recorded rows (per-slot `max(configured, recorded)`), run the strict solve first, re-solve once on failure, and set the `limits_relaxed` warning and `relaxed_limits`. Verify: new tests for EV import above limit and PV surplus above export score with `limits_relaxed`.
- [x] 2.3 Replace `solver_not_optimal` with `infeasible_with_recorded_limits` or `solver_time_limit` after a failed relaxed solve; add `relaxed_limits: []` to `base_record`; bump `BENCHMARK_VERSION` to 3. Verify: test of a day that stays infeasible stores the specific reason.
- [x] 2.4 Tests in `tests/backend/test_battery_benchmark.py` (reuse `_config`, `_day_rows`, `_run`) and `tests/backend/test_battery_benchmark_service.py`: normal day unchanged (no warning, same values), full-swing day scored, v2 and failed days are not done. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/backend/test_battery_benchmark.py tests/backend/test_battery_benchmark_service.py -q` passes.
- [x] 2.5 Frontend: add `limits_relaxed` text, the two reason labels and optional `relaxed_limits` typing in `CommandDomains.tsx` and `api.ts`, following `docs/design-system/AI_GUIDELINES.md`; add a case to `CommandDomains.test.tsx`. Verify: `pnpm --dir frontend test` for that file passes.

## 3. Dead error-correction leftovers (Item C)

- [x] 3.1 Add the three keys to `DEPRECATED_NESTED_KEYS` in `backend/config_migration.py`; confirm `auto_tune_enabled` has no readers. Verify: grep shows none outside docs, archives and debugging dumps.
- [x] 3.2 Create `tests/config/test_dead_error_correction_migration.py` modelled on `test_dead_load_safety_margin_migration.py`: removes all three keys, keeps siblings, idempotent, tolerates None and non-dict, full `_migrate_config` round trip does not re-add. Verify: file passes.
- [x] 3.3 `git rm ml/models/defaults/load_error.lgb`; add the idempotent purge to `ml/bootstrap.py` (runtime dir, its `defaults/`, `backup/*/`, logged). Verify: new bootstrap test shows only the two stale files removed, real models kept, second run a no-op.
- [x] 3.4 Remove `optional_models` and its loop from `scripts/health_check.py`; check tests that expect `load_error.lgb` in defaults. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests -q -k "health or bootstrap or startup"` passes.

## 4. Verification

- [x] 4.1 Run all targeted tests added or touched in groups 1 to 3 and confirm they pass.
- [x] 4.2 Run `./scripts/lint.sh` and confirm it passes end to end (ruff, format, pyright, full pytest, frontend format, lint, typecheck, tests).
- [x] 4.3 Run `openspec validate forecast-slot-benchmark-and-dead-config-fixes --strict` and confirm it passes.
