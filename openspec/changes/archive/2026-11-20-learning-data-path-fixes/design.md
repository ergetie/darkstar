# Design

## Context

See proposal.md for the problems. Evidence on `main`: overlay read at `planner/inputs/learning.py:37`, applied at `planner/pipeline.py:1562-1565` and `:1631-1635`, passed on at `:1736` to `apply_safety_margins` (`planner/inputs/data_prep.py:185`), where `overlays` is a parameter only. `slot_start` is stored as a local ISO string with UTC offset by every writer (`store.py:159-161` for observations, `store_slot_prices` at `store.py:90-93`), so strings sort by wall clock, not by instant, around DST changes (autumn: `02:30+02:00` is the earlier instant but sorts after `02:15+01:00` as text).

PR #9 branch `fix/learning-loop-reflex-and-data` is based on an older `main`: a tip-to-tip diff against `main` reverts unrelated work (for example `unmeasured_device_clause` in `store.py`). Use `gh pr diff 9` hunks only; never merge or cherry-pick whole files from the branch.

## Goals / Non-Goals

**Goals:** no stale learned override of config; `temp_c` survives; correct last-observation time; no fabricated API data.
**Non-Goals:** Reflex scheduling or any Reflex status fields (backlog item "[Learning] Replace Reflex With Measured, Stored Learned Parameters"); dropping `learning_daily_metrics`; any other issue #8 finding.

## Decisions

1. **Remove the overlay path, not a freshness cut.** Nothing writes `learning_daily_metrics` (no writer since fad904e3), so any freshness window just defers the same stale-override problem to a dead mechanism. Remove: `planner/inputs/learning.py` (whole file), the import at `pipeline.py:39`, the load at `:1562-1565`, the override block at `:1631-1635`, and `LearningStore.get_latest_metrics` (`store.py:1518-1533`, the only other reader). `s_index_cfg["base_factor"]` is then used directly. `apply_safety_margins` keeps its `overlays` parameter (signature change not needed for this fix) and `pipeline.py:1736` passes `{}`. Alternative rejected: PR #9's 2-day cut keeps dead code and a hidden override path.
2. **Remove `GET /api/learning/daily_metrics`** (`backend/api/routers/learning.py:157-185`). Frontend check: `frontend/src/lib/api.ts:1703` (`learningDailyMetrics`) and type `:400` have no caller anywhere else in `frontend/src`. Delete both. Remove the now-unused `LearningDailyMetric` import in the router. Update the route lists in `scripts/verify_slow.py:58-59`, `scripts/verify_arc1_routes.py:78-79` and the call in `scripts/benchmark_async.py:73`.
3. **Keep the table and ORM model.** `learning_daily_metrics` (`backend/learning/models.py:168`, baseline migration) and `LearningDailyMetric` stay; schema changes need separate approval. A follow-up can drop them. `docs/ARCHITECTURE.md:1010` stays accurate, and `docs/` is not edited.
4. **`temp_c` COALESCE** exactly as PR #9: `"temp_c": func.coalesce(stmt.excluded.temp_c, SlotForecast.temp_c)` at `store.py:512`, mirroring `pv_ml_residual_raw_kwh` in the same dict. Unknown stays NULL. Reuse PR #9's `tests/ml/test_temp_c_persistence.py` unchanged and add the "never measured stays NULL, not 0" case.
5. **Last observation = latest completed recorded slot, compared as instants in SQL.**
   - Signature `get_last_observation_time(self, now: datetime | None = None)`; `now` defaults to `datetime.now(self.timezone)`.
   - Cutoff: `(now - timedelta(minutes=SLOT_MINUTES))` converted to UTC, formatted `%Y-%m-%d %H:%M:%S`. Import `SLOT_MINUTES` from `backend.learning.pv_cleaning` (store already imports that module; `backfill.py` imports the store, so importing from `backfill` would be circular).
   - Query: `SELECT slot_start WHERE (quality_flags IS NOT NULL OR soc_end_percent IS NOT NULL) AND datetime(slot_start) <= :cutoff ORDER BY datetime(slot_start) DESC LIMIT 1`. SQLite's `datetime()` normalises a `+HH:MM` suffix to UTC (verified on SQLite 3.46: `02:30+02:00` gives `00:30`, `02:30+01:00` gives `01:30`), so ordering and the cutoff are correct across DST. Plain string comparison (PR #9's `slot_start <= now_iso`) is rejected: it breaks inside the autumn repeated hour and at offset changes. All writers store offset-aware strings, so `datetime()` never sees a naive value.
   - Cost: `datetime(slot_start)` cannot use the primary-key index, so this is a scan of `slot_observations` (about 35k rows per year, retention applies) at startup/status time only. Accepted.
   - The returned string is parsed as before (`fromisoformat`, `astimezone(self.timezone)`); the naive branch stays for safety.
   - PR #9's `quality_flags OR soc_end_percent` filter is kept: recorder and backfill rows always carry `quality_flags`; legacy rows carry SoC; price-only rows carry neither.
   - `BackfillEngine.run` (`backfill.py:289-292`) computes `now` first and passes it: `get_last_observation_time(now)`. `LearningEngine.get_status` (`engine.py:111`) uses the default.
6. **Deterministic tests.** No wall-clock reads in tests: they build rows at fixed local datetimes (`Europe/Stockholm`) and pass an explicit `now`. The `test_backfill.py` mock accepts the new argument. The DST test uses 2026-10-25 slots (`02:30+02:00` and `02:15+01:00`) and 2026-03-29 for spring.
7. **Remove `GET /api/learning/loops`** (`learning.py:140-155`) entirely. Its four loops (`pv_forecast`, `load_forecast`, `s_index`, `arbitrage`) are invented: no table stores per-loop runs, `status` is hard-coded `"active"`, `error` is always None. Real run data exists only as ML training status (`/api/learning/training-status`, `learning_runs`), which the frontend already uses separately. Nothing in `frontend/src` calls `learningLoops` (`api.ts:1705`; type `:476` has different loop names than the endpoint), so remove the endpoint, the client function and `LearningLoopsResponse`, and the two script route entries. Reporting `last_run` from `learning_runs` for `pv_forecast`/`load_forecast` while leaving `s_index`/`arbitrage` empty was rejected: a partial mapping of fictional loops is still fabricated structure.
8. **Comment fix only** at `scheduler_service.py:450`: `# Default Tue/Fri (weekday() 1 and 4)`; the default values `[1, 4]` do not change, to keep existing users' schedule.
9. **Commit attribution.** The final commit uses a `Co-authored-by: Cm0n89 <Cm0n89@users.noreply.github.com>` trailer (address from `gh api repos/ergetie/darkstar/pulls/9/commits`, all four commits). No other attribution lines are added by this change's text.

## Risks / Trade-offs

- A user who relied on the stale learned base factor now gets their configured value; this is the intended fix and is called out in release notes by the maintainer (not edited here).
- External scripts hitting the two removed endpoints get 404; no in-repo consumer remains after the script updates.
- First backfill after upgrade may fetch up to 10 days (`MAX_BACKFILL_DAYS`) of history for installs that never backfilled; this is the capped, intended behaviour.
