# Proposal

## Why

An upgrade can currently destroy a user's data with no way back, and the planner database grows without bound. The Docker start-up backup (`scripts/docker-entrypoint.sh:81-92`) copies `/data/planner_learning.db`, but the compose install keeps the database at `/app/data` and the backup folder inside the container layer, so it is skipped or lost on container recreate. It is a plain `cp` of a WAL database taken on every start, never pruned, and the migration runs even if it fails. The add-on runs `alembic upgrade head` with no backup (`darkstar/run.sh:78-90`, identical in `darkstar-dev/run.sh`). The updater leaves a migrated database and a broken container in place ("no automatic rollback was done", `updater/service.py:360-365`). Separately, the local database is 819 MB, 78% of it `execution_log` (365k rows), because nothing prunes it and nothing ever vacuums. Both are beta-exit P0 items (`docs/reports/BETA_EXIT_READINESS.md` section 3).

## What Changes

- New `backend.db_safety` module and CLI: consistent SQLite online backup taken only before a pending migration, 3 kept, in a persistent `backups/` folder next to the database; the migration is aborted when the backup fails; a failed migration restores the backup it just took.
- Docker entrypoint and both add-on `run.sh` files call the CLI instead of `cp` / bare `alembic upgrade head`.
- One-time switch to `auto_vacuum=INCREMENTAL` (single full `VACUUM` at start-up, after a verified backup, space-checked, idempotent, never fatal).
- Retention pruning for `execution_log` (30 days), `planner_debug` (14 days), `s_index_history` (365 days) and, opt-in only, `slot_observations`, `slot_forecasts`, `slot_plans`, `price_forecasts`, `learning_runs` (kept forever by default), run once a day by a new background service, followed by bounded `PRAGMA incremental_vacuum` batches. No full `VACUUM` at runtime. The two existing ad-hoc prunes (`s_index_history` inline, `learning_runs` after training) move into it.
- Updater self-recreate: after a successful apply that changed the updater or the compose file, a detached helper container rebuilds and recreates the updater (one attempt per change, old updater kept on failure).
- Updater rollback: if `up -d` fails or the new container is not healthy in 5 minutes, restore the previous checkout, rebuild and restart it, and put back the pre-migration database backup that this apply created.
- Removal of the dead `ExecutionLog.cleanup_old_records`, the unused `ExecutorConfig.history_retention_days` field, `cleanup_learning_runs` and the inline s_index prune; the key `executor.history_retention_days` is now read by the maintenance service.
- New config keys (approved, defaults in `config.default.yaml`): `learning.retention_days` (0), `learning.price_forecast_retention_days` (0), `learning.learning_runs_retention_days` (0), `learning.s_index_history_retention_days` (365), `learning.planner_debug_retention_days` (14).
- `docker-compose.yml`: updater `data` mount becomes read-write so it can restore the database.
- **BREAKING (behaviour)**: rows older than the active retention windows are deleted for good; the old start-up `cp` backup is gone (replaced by the pre-migration backup); `learning_runs` is no longer cut at 30 days, so the learning graduation level can now accumulate.
- Limitation: the first update that ships this is applied by the already deployed (old, read-only-mount, no-rollback) updater; see design D17.

## Capabilities

### New Capabilities
- `database-backup-rollback`: consistent pre-migration backup with bounded retention, abort/restore on failure, in Docker and add-on start-up paths.
- `database-retention`: per-table retention, scheduled cleanup, one-time incremental auto-vacuum switch and bounded incremental vacuum.

### Modified Capabilities
- `docker-self-update`: automatic rollback of code and database when the updated container fails to start or become healthy.

## Impact

- Code: new `backend/db_safety.py`, `backend/services/db_maintenance_service.py`; edits to `backend/main.py`, `planner/observability/logging.py`, `ml/training_orchestrator.py`, `backend/learning/store.py`, `scripts/docker-entrypoint.sh`, `darkstar/run.sh`, `darkstar-dev/run.sh`, `updater/service.py` (+ new `updater/db_restore.py`, `updater/self_update.py`), `frontend/src/components/UpdateCard.tsx`, `frontend/src/lib/api.ts`, `executor/history.py`, `executor/config.py`, `docker-compose.yml`, `config.default.yaml`.
- Docs (ask-first directory): `docs/OPERATIONS.md` line 39 and a restore how-to.
- No alembic migration and no table/column changes.
- Backlog: entries "Upgrades Cannot Be Undone" and "Database Grows Forever" removed, and the rollback part removed from the Updater entry (signing and pinned origin stay).
