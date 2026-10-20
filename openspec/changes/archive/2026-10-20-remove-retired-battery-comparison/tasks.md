# Tasks

## 1. Backend removal

- [x] 1.1 Remove all dead symbols from `backend/battery_comparison.py`, keeping only the retained provenance helpers listed in design.md, and drop unused imports (verify: `ruff check backend/battery_comparison.py` clean; `python -c "import backend.learning.store, backend.comparison_history"` succeeds)
- [x] 1.2 Delete `backend/baseline.py` (verify: `grep -rn "backend.baseline\|from backend import baseline" --include=*.py .` returns nothing)

## 2. Tests

- [x] 2.1 Delete `tests/test_battery_comparison_segmentation.py` and `tests/backend/test_baseline.py` (verify: files gone)
- [x] 2.2 In `tests/test_battery_comparison.py` delete dead-only tests, keep the three live-only tests, rewrite the two mixed tests to live symbols, keep `recording()`/`trusted_flags()` without removed models (verify: `UV_NO_SYNC=1 uv run python -m pytest tests/test_battery_comparison.py tests/ml/test_learning_engine.py -q` passes)
- [x] 2.3 Rewrite `tests/test_comparison_history.py::test_real_wal_annotation_undo_preserves_history_calibration_eligibility` to count `calibration_eligible` rows (verify: that test passes)
- [x] 2.4 `git mv tests/api/test_battery_comparison_api.py tests/api/test_grid_only_comparison_api.py`; update the module docstring (line 1) to drop "retired"; in the test at lines 91-133 delete lines 107-114 (`fail`, `import backend.baseline`, `import backend.battery_comparison`, both `monkeypatch.setattr`), rename it to `test_request_reads_only_selected_period_and_does_not_write` and drop its unused `monkeypatch` parameter (verify: `UV_NO_SYNC=1 uv run python -m pytest tests/api/test_grid_only_comparison_api.py -q` passes, 7 tests incl. 3 parametrized; `grep -nE "baseline|battery_comparison|simulate|calibrat|monkeypatch" tests/api/test_grid_only_comparison_api.py` only matches the `monkeypatch` use in the started-slot test and the `..._battery_comparison_unavailable` test name)
- [x] 2.5 In `tests/api/test_energy_cost_series.py` delete lines 82-84 (`"baseline"`/`"battery_comparison"` absence and `baseline_cumulative_net_cost_sek` per-point absence) (verify: `UV_NO_SYNC=1 uv run python -m pytest tests/api/test_energy_cost_series.py -q` passes; `grep -nE "baseline|battery_comparison" tests/api/test_energy_cost_series.py` returns nothing)

## 2b. Frontend guards

- [x] 2b.1 In `frontend/src/lib/api.ts` `parseCostSeriesResponse` delete line 789 (`'baseline' in value || 'battery_comparison' in value` rejection) and line 793 (`baseline_` per-point key rejection); leave all other validation unchanged (verify: `grep -nE "'baseline' in|battery_comparison|baseline_" frontend/src/lib/api.ts` returns only the unrelated `active_forecast_version` type `'baseline_7_day_avg'`; the unrelated `mode?: 'baseline' | 'personalized'` type also stays)
- [x] 2b.2 Delete the test `rejects retired baseline and battery-comparison fields instead of falling back` (`frontend/src/lib/api.cost-series.test.ts:125-129`) and the `Without Darkstar` assertion (`frontend/src/components/CostSeriesChart.test.tsx:116`) (verify: `grep -rnE "battery_comparison|Without Darkstar|retired" frontend/src` returns nothing)
- [x] 2b.3 Run frontend checks. There is no pnpm on this machine; `frontend/package.json` defines `test` as `vitest run` and `lint` as eslint, and CI (`.github/workflows/ci.yml`) and `scripts/lint.sh` run `pnpm test` in `frontend/`. Locally use the installed binaries: `cd frontend && ./node_modules/.bin/vitest run src/lib/api.cost-series.test.ts src/components/CostSeriesChart.test.tsx`, then `./node_modules/.bin/vitest run`, `./node_modules/.bin/eslint . --report-unused-disable-directives --max-warnings 0` (verify: all pass; CI `pnpm test` covers the same suite)

## 3. Rename

- [x] 3.1 `git mv backend/battery_comparison.py backend/observation_provenance.py` and `git mv tests/test_battery_comparison.py tests/test_observation_provenance.py` (verify: old paths gone, new paths tracked)
- [x] 3.2 Update imports in `backend/learning/store.py`, `backend/comparison_history.py` and `tests/ml/test_learning_engine.py`; leave `battery_comparison` API field references untouched (verify: `grep -rnE "backend\.battery_comparison|tests\.test_battery_comparison|from backend import battery_comparison|battery_comparison" --include=*.py backend tests scripts` returns only the test name `test_nonfinite_configured_cycle_cost_makes_battery_comparison_unavailable`; `UV_NO_SYNC=1 uv run python -m pytest tests/test_observation_provenance.py tests/ml/test_learning_engine.py tests/test_comparison_history.py -q` passes)

## 4. Verification

- [x] 4.1 Grep the repo (excluding `openspec/changes/archive` and docs history) for every removed symbol name and `baseline.py`; no code references remain (verify: grep output empty)
- [x] 4.2 Grep for retired-feature absence checks and guards: `grep -rnIE "baseline_cumulative|'baseline' in|battery_comparison|Without Darkstar|simulate_self_use|fit_calibration" backend tests frontend/src --exclude-dir=static` returns only `tests/api/test_grid_only_comparison_api.py` test name `test_nonfinite_configured_cycle_cost_makes_battery_comparison_unavailable` (`backend/static` is a stale built bundle, not source; `self_use` is excluded because `tests/executor/test_executor_history.py` uses it as a live inverter mode)
- [x] 4.3 Run `./scripts/lint.sh` and the full backend test suite (verify: both pass)
