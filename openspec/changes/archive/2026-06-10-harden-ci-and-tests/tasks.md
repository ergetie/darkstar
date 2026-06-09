## 1. Establish the pyright baseline (do first — gates D2)

- [x] 1.1 Run repo-wide strict pyright locally (`uv run pyright`) and record the error count
- [x] 1.2 If clean: proceed to the CI gate as-is. If not clean: list the pre-existing errors and decide (with operator) whether to clear them in this change or carve out a follow-up; clear in-scope errors

## 2. CI quality gate (#3 → ci-quality-gate)

- [x] 2.1 In `.github/workflows/ci.yml`, replace the API-only test step with `uv run python -m pytest` over the whole `tests/` tree
- [x] 2.2 Add a dedicated pyright job that runs the strict config from `pyproject.toml`
- [x] 2.3 Add dependency/uv caching so the full suite stays fast
- [x] 2.4 Mark the test job and the pyright job as required checks for merge (branch protection)
- [ ] 2.5 Verify on a throwaway PR: a deliberately broken planner test fails CI; a deliberate pyright error fails CI

## 3. WAL at startup (#37 → database-concurrency-safety)

- [x] 3.1 In `backend/main.py` lifespan, call `await store.ensure_wal_mode()` right after `LearningStore` init, independent of `executor.config.enabled`
- [x] 3.2 Confirm `store.ensure_wal_mode()` is idempotent and safe on an already-WAL DB
- [x] 3.3 Add a test: starting with the executor disabled leaves `planner_learning.db` in WAL mode

## 4. Offload sync DB reads + busy-timeout (#38 → database-concurrency-safety)

- [x] 4.1 Confirm the unverified residual: does `ml/training_orchestrator.train_all_models` block the event loop? Record the finding; expand scope here only if confirmed
- [x] 4.2 Wrap the synchronous reads in `backend/api/routers/price_forecast.py` (`:99`, `:155`, `:233`, `:281`) and `backend/core/price_outlook.py` (`:46`, `:194`) in `asyncio.to_thread`
- [x] 4.3 Add `timeout=30` to the price-forecast `sqlite3.connect` calls
- [x] 4.4 Wrap the sync SQLAlchemy reads in `backend/api/routers/executor.py` history/stats routes in `asyncio.to_thread`
- [x] 4.5 Add a test or smoke check confirming the routes still return identical results

## 5. print → logger + lint guard (#11 → test-hygiene)

- [x] 5.1 Replace `print(...)` at `planner/inputs/weather.py:62` with `logger.warning(...)` using the module logger
- [x] 5.2 Replace `print(...)` at `ml/evaluate.py:100` with `logger.warning(...)`
- [x] 5.3 Enable ruff rule T201 (flake8-print) for `backend/`, `planner/`, `ml/`, `executor/`; exempt `scripts/` and CLI entrypoints
- [x] 5.4 Run ruff; confirm no remaining `print` violations in the guarded packages

## 6. Characterization tests for untested infra (#5 → test-hygiene)

- [x] 6.1 Write characterization tests for `backend/ha_socket.py` (connect, message handling, reconnection) against a mocked socket
- [x] 6.2 Write characterization tests for `backend/services/planner_service.py` (orchestration behavior)
- [x] 6.3 Write characterization tests for `backend/services/recorder_service.py` (record → sleep-to-boundary loop behavior)
- [x] 6.4 Confirm the new tests run and pass under the full-suite CI job from task 2

## 7. Verify & close

- [x] 7.1 Run the full suite locally (`uv run python -m pytest`) — confirm still green (≥1051 passing)
- [x] 7.2 Confirm no behavior change to planning/forecasting/control (only CI, logging, DB-access touched)
- [x] 7.3 Run `openspec validate harden-ci-and-tests`
