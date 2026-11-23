# Tasks

## 1. Per-entity revert tracking in the executor

- [x] 1.1 In `executor/actions.py`, add `_verified_command` per resolved entity id (next to `_last_write_at`), set on a write with `verification_success is True`, removed on an unverified or failed write, refreshed without counting when the entity is already at target. Restrict to non-`NUMBER_DOMAINS` entities from the profile mode actions. Expose revert events (entity, commanded, observed) through a drain method. Verify with unit tests: revert counted per entity, Deye switch revert counted on the switch only, transition not counted, own write and 30 s age not counted, unverified write sets no baseline, unavailable ignored, `CONFIGURE_ME` skipped, numeric entity ignored.
- [x] 1.2 In `executor/actions.py`, add `clear_baselines()` and drop baselines for entities absent from the executed mode's actions at the end of `execute()`; clear on `update_config` when profile or entity mapping changes. Verify with tests incl. Sungrow `export_power_limit_switch` outside export mode.
- [x] 1.3 In `executor/engine.py`, feed events into per-entity rolling windows (`max(60 min, 4 x interval)`, threshold 3 per entity), call `clear_baselines()` in every non-writing path (manual override, pause, automation toggle off, disabled, shadow), and persist/clear the `executor_mode_revert_notice` `system_state` key with the per-entity list. Verify with engine tests incl. manual override, restart, and events spread over two entities.
- [x] 1.4 Send one notification per episode naming the entity or entities, gated by `on_inverter_mode_revert`. Verify with a test for toggle on and off.

## 2. Toggle plumbing

- [x] 2.1 Add `on_inverter_mode_revert` to `NotificationConfig`, `load_executor_config`, `config.default.yaml` (default true, commented), and the executor router GET/PUT. Verify with config and API tests including absent key = true.
- [x] 2.2 Add the toggle to `Executor.tsx`, `pages/settings/types.ts`, `search/guides.ts`, and frontend types. Verify with the existing notification frontend tests extended and `pnpm` lint/typecheck.

## 3. Revert health warning

- [x] 3.1 Add an evaluator in `backend/monitors.py` and a `health_issues()` entry with code `INVERTER_MODE_REVERT` carrying `details.entities` (stale notices dropped). Verify with monitor tests and `tests/backend/test_health.py`.

## 4. Executor health check fix

- [x] 4.1 In `backend/api/routers/executor.py`, add `peek_executor_instance()` (no creation) and extract `executor_health_snapshot(executor)` from `get_health`, with `should_be_running = enabled and not paused` and `is_healthy` not penalising a paused or disabled executor whose thread is alive. Before changing the `/api/executor/health` output, check its consumers in `frontend/src/lib/api.ts` and `Dashboard.tsx`. Verify with route tests for paused, disabled, dead-thread and error cases.
- [x] 4.2 Rewrite `HealthChecker.check_executor` in `backend/health.py` to use the snapshot, emit `EXECUTOR_NOT_RUNNING` (critical) and `EXECUTOR_LAST_RUN_FAILED` (warning), log failures at warning level, and never create an executor.
- [x] 4.3 Add tests in `tests/backend/test_health.py` that call `check_executor` with a patched `peek_executor_instance` (so a missing or renamed function fails the test), covering dead thread, paused, disabled, last run failed, no instance, and an internal failure that logs a warning and returns no issues.

- [x] 4.4 In `check_executor`, add `EXECUTOR_NOT_INITIALIZED` (critical, executor enabled in config but `peek_executor_instance()` is None, never create) and `EXECUTOR_STALE` (warning, threshold `max(3 x interval, 600 s)` as named constants, from `status.last_run_at`; snapshot exposes the age fields). Verify with tests: no instance enabled/disabled, stale vs recent, paused/disabled not stale, no tick yet not stale.
- [x] 4.5 In `backend/api/routers/config.py` after `executor.reload_config()`, start the executor when `executor.config.enabled` and the thread is not alive; never create an instance. Verify with tests: enabled starts, already running does not start again, disabled does not start and leaves the loop idle (loop idle path covered by an engine test), no instance creates nothing, start failure does not fail the save.

## 5. `s_index.base_factor` save warning

- [x] 5.1 Add the range check to `_validate_config_for_save` in `backend/api/routers/config.py` (warning, field `s_index.base_factor`, `max_factor` default 1.5, non-number `max_factor` skips the upper bound). Verify with tests in `tests/config/test_config_validation.py`: 0.9, 1.6 vs 1.5, valid 1.1, absent section, non-numeric max_factor, and that the save is not blocked.

## 6. Docs and final checks

- [x] 6.1 Edit `docs/BACKLOG.md` (approved by the user) to remove the items "[Executor] Detect Inverter Mode Reverts And Power Mismatch" and "[Settings] Warn About Out-Of-Range And Learning-Contradicted Settings" (the settings item is closed as already covered by the Learned Parameters section, `capacity_change_warning` and `pv_site_sanity.py`). Add user-manual notes for the revert warning if the manual lists health warnings. Verify by reading the diff.
- [x] 6.2 Run `./scripts/lint.sh`, the targeted pytest files with `UV_NO_SYNC=1`, the frontend tests, and `npx openspec validate --all --strict`. All pass.
