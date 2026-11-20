# Tasks

Port PR #9 changes by hunk (`gh pr diff 9`); its branch is stale against `main`, so never copy whole files from it. Do not touch Reflex scheduling or `backend/api/routers/schedule.py`.

## 1. Remove the stale learning overlay

- [x] 1.1 Delete `planner/inputs/learning.py`; remove the import (`planner/pipeline.py:39`), the `load_learning_overlays` call (`:1562-1565`) and the override block (`:1631-1635`); pass `{}` to `apply_safety_margins` (`:1736`) and fix its docstring in `planner/inputs/data_prep.py`. Verify with `UV_NO_SYNC=1 uv run python -m pytest tests/planner -n auto -q` and `grep -rn "load_learning_overlays" --include=*.py .` returning nothing.
- [x] 1.2 Delete `LearningStore.get_latest_metrics` (`backend/learning/store.py:1518`), the `GET /api/learning/daily_metrics` route and unused `LearningDailyMetric`/`desc` imports in `backend/api/routers/learning.py`, `learningDailyMetrics` and `LearningDailyMetricsResponse` in `frontend/src/lib/api.ts`, and the entries/calls in `scripts/verify_slow.py`, `scripts/verify_arc1_routes.py`, `scripts/benchmark_async.py`. Keep the `learning_daily_metrics` table and `LearningDailyMetric` model; verify with `git diff --stat` showing no `alembic/` or `models.py` change.
- [x] 1.3 Add `tests/planner/test_no_learning_overlay.py`: build a learning DB with a `learning_daily_metrics` row `s_index_base_factor=1.4066` and config `s_index.base_factor=1.1`, run the S-Index step of `generate_schedule` in `mode="full"` with `learning.enable: true`, and assert the base factor used is 1.1. Verify it fails on `main` (1.4066 used) and passes now.

## 2. Keep forecast `temp_c`

- [x] 2.1 Apply the PR #9 hunk at `backend/learning/store.py:512` (`func.coalesce(stmt.excluded.temp_c, SlotForecast.temp_c)` with its comment). Add PR #9's `tests/ml/test_temp_c_persistence.py` and a case that a slot never given a temperature stays NULL (`IS NULL`, not 0). Verify the re-upsert test fails on `main` and all pass now.

## 3. Last observation time

- [x] 3.1 Rewrite `get_last_observation_time(self, now: datetime | None = None)` in `backend/learning/store.py:614` per design decision 5 (`quality_flags`/`soc_end_percent` filter, `datetime(slot_start) <= cutoff_utc`, ordered by `datetime(slot_start) DESC LIMIT 1`, `SLOT_MINUTES` imported from `backend.learning.pv_cleaning`); keep PR #9's explanatory docstring.
- [x] 3.2 Pass the same `now` from `BackfillEngine.run` (`backend/learning/backfill.py:289-292`, compute `now` before the call) and update the `get_last_observation_time` mock in `tests/ml/test_backfill.py` for the new argument; add a backfill test where the store holds a recorded slot 6 hours old plus future price rows and assert history is requested for the missing slots (fails on `main` with "Data is up to date").
- [x] 3.3 Add `tests/ml/test_last_observation_time.py` from PR #9, rewritten with fixed datetimes and an injected `now` (no `datetime.now` in the test): future price rows ignored; price-only rows give `None`; price merged into a recorded slot counts once completed; a slot that started 10 minutes before `now` does not count (the previous completed one does); a slot exactly 15 minutes old counts; autumn DST (`2026-10-25T02:30:00+02:00` vs `02:15:00+01:00`, later instant wins) and spring DST (`2026-03-29`) cases. Verify the future-row, in-progress and DST tests fail on `main` and pass now.

## 4. Loops endpoint and comment

- [x] 4.1 Delete `GET /api/learning/loops` (`backend/api/routers/learning.py:140-155`), `learningLoops` and `LearningLoopsResponse` in `frontend/src/lib/api.ts`, and the route entries in `scripts/verify_slow.py` and `scripts/verify_arc1_routes.py`. Add a test in `tests/api` (existing router test pattern) asserting 404 for `/api/learning/loops` and `/api/learning/daily_metrics`. Verify with `pnpm --dir frontend exec tsc --noEmit` (or the project's frontend type-check script) and `grep -rn "learning/loops" frontend/src backend` returning nothing.
- [x] 4.2 Change the comment at `backend/services/scheduler_service.py:450` to `# Default Tue/Fri (weekday() 1 and 4)`; no value changes. Verify `git diff backend/services/scheduler_service.py` shows that one line only.

## 5. Final checks and commit

- [x] 5.1 Run `./scripts/lint.sh` and `UV_NO_SYNC=1 uv run python -m pytest -n auto tests/ml tests/planner tests/api tests/services -q`; confirm all pass and `git status` shows no runtime files (`*.db`, `schedule.json`).
- [ ] 5.2 On user approval to commit, use a conventional message (single-line `-m` strings) and add the trailer `Co-authored-by: Cm0n89 <Cm0n89@users.noreply.github.com>` (the address on PR #9's commits); add no other attribution. Do not touch Reflex code, `docs/`, or push unless instructed.
