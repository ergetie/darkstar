# Proposal

## Why

GitHub issue #8 (Cm0n89) and PR #9 report data-path bugs in the learning code. The maintainer's reviewer verified each against `origin/main`:

- **Stale overlay.** `learning_daily_metrics` has had no writer since fad904e3, yet `load_learning_overlays` (`planner/inputs/learning.py:12-49`) applies `s_index_base_factor` from the latest row and `planner/pipeline.py:1631-1635` lets it override `s_index.base_factor`. Production had 1.4066 from 2026-03-15 silently overriding the configured 1.1, and the user cannot see or change it.
- **`temp_c` wiped.** The `store_forecasts` upsert sets `temp_c = excluded.temp_c` (`backend/learning/store.py:512`) and `bin/run_planner.py:73` re-upserts planner forecast rows that carry no `temp_c`. Every planner run nulls the forward pass's temperatures across the price horizon.
- **Backfill never runs.** `get_last_observation_time` (`store.py:614-624`) is a plain `MAX(slot_start)`. `store_slot_prices` (`bin/run_planner.py:67`) writes future price-only rows into `slot_observations`, so the "last observation" is in the future. `BackfillEngine.run` (`backend/learning/backfill.py:290-301`) then sees a negative gap, logs "Data is up to date" and never fills downtime gaps. `LearningEngine.get_status` (`engine.py:111`) reports the same future time as `last_observation`.
- **Wrong comment.** `_compute_next_training` (`backend/services/scheduler_service.py:450`) says `[1, 4]` is Mon/Thu; `weekday()` makes it Tue/Fri.
- **Fake loop status.** `/api/learning/loops` (`backend/api/routers/learning.py:140-155`) returns a hard-coded `status: "active"` and `last_run: None` for four invented loops.

This change builds on PR #9 by Cm0n89: its `temp_c` COALESCE and its tests are reused as is, and its observation-time filter is the base of fix 3 (made completed-slot-only and DST-correct). The overlay fix is a stronger variant of PR #9's 2-day freshness cut. The final commit carries a `Co-authored-by:` trailer for Cm0n89.

## What Changes

- Remove the learning overlay path entirely: `load_learning_overlays`, its call and override in `PlannerPipeline`, `LearningStore.get_latest_metrics`, the `/api/learning/daily_metrics` endpoint and its unused frontend client and type. `s_index.base_factor` comes from config only. The `learning_daily_metrics` table and its model stay (no schema change).
- `store_forecasts` keeps the existing `temp_c` when the new row has none (`COALESCE`). Unknown stays NULL, never 0.
- `get_last_observation_time(now)` counts only recorder/backfill rows (`quality_flags` set, or legacy `soc_end_percent` set) whose slot has completed (`slot_start <= now - 15 min`), compared as instants so DST offsets cannot misorder rows. `now` is injectable.
- Remove `/api/learning/loops` and its unused frontend client and type. There is no stored per-loop run data, so no `last_run` can be real.
- Fix the `run_days` default comment to Tue/Fri.
- Regression tests that fail on `main` and pass with the fixes.

## Capabilities

### New Capabilities
- `learning-data-integrity`: what the learning store and its consumers may treat as learned or observed data (no stale learned overrides, forecast temperatures kept, observation time = latest completed recorded slot, no fabricated loop status).

### Modified Capabilities
None.

## Impact

- Code: `planner/inputs/learning.py` (deleted), `planner/pipeline.py`, `planner/inputs/data_prep.py` (docstring only), `backend/learning/store.py`, `backend/learning/backfill.py`, `backend/api/routers/learning.py`, `backend/services/scheduler_service.py` (comment line only), `frontend/src/lib/api.ts`, `scripts/verify_slow.py`, `scripts/verify_arc1_routes.py`, `scripts/benchmark_async.py`.
- Tests: new `tests/ml/test_last_observation_time.py`, `tests/ml/test_temp_c_persistence.py` (from PR #9), `tests/planner/test_no_learning_overlay.py`, `tests/api/` route-removal check; `tests/ml/test_backfill.py` extended.
- API: `GET /api/learning/loops` and `GET /api/learning/daily_metrics` are removed (no frontend consumer; scripts updated). `GET /api/learning/status` `last_observation` becomes correct.
- No config keys, no DB schema change, no new dependency. `docs/` is not touched (`docs/ARCHITECTURE.md:1010` still lists the table, which still exists).
- Behaviour change on upgrade: a user whose planner was silently using a stale learned `s_index_base_factor` now plans with their configured `s_index.base_factor`.

## Out of Scope

- Scheduling Aurora Reflex and every part of PR #9's Reflex work: the 04:30 job in `backend/services/scheduler_service.py`, `reflex_enabled`/`next_reflex_at`/`last_reflex_at`/`last_reflex_status` in `/api/scheduler/status` (`backend/api/routers/schedule.py`). That is replaced by the backlog item "[Learning] Replace Reflex With Measured, Stored Learned Parameters" in `docs/BACKLOG.md`.
- PR #9's `ha_client.py` load-profile rounding change and its 2-day freshness cut for the overlay (superseded by removal).
- All other findings from issue #8 (already in `docs/BACKLOG.md`).
- Dropping the `learning_daily_metrics` table (schema change needs separate approval).
