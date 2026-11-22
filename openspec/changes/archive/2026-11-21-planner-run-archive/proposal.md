# Proposal

## Why

Past planner decisions cannot be reconstructed: `schedule.json` is overwritten every run, `slot_plans`/`slot_forecasts` keep only the last value per slot, `debug.enable_planner_debug` stores a 30-slot sample, and the log rotates and is wiped on add-on restart. The cmon89 investigation (2026-10-06) could not replay the plan that was actually made. A per-run archive lets a maintainer re-solve any past run offline (verified: re-solving an archived `schedule.json` with the offline Kepler reproduces the real plan, 0/122 slots differ) and lets a user hand the data over for support from the Debug page.

## What Changes

- Archive every planner run made by the planner service as one gzip JSON file under `data/plan_archive/`, with full inputs, the resulting plan, initial SoC, safety floor, config version and redacted effective config, solver status, the planner error (when the run failed) and the executor errors seen since the previous archived run.
- Failed runs are archived too (error code, message, details, plus whatever inputs had been gathered).
- New config keys `debug.plan_archive_enabled` (default `true`) and `debug.plan_archive_retention_days` (default `60`, minimum `7`). Files older than the retention window are deleted after every archive write.
- New Debug page "Plan archive" card: shows run count, size and date range; downloads a zip of the archive (all, last 7 days or last 24 hours); clears the archive after confirmation.
- New endpoints `GET /api/debug/plan-archive`, `GET /api/debug/plan-archive/download`, `DELETE /api/debug/plan-archive`.
- `save_schedule_to_json` returns the output dict it wrote (previously `None`) so the archive stores exactly what `schedule.json` contains.
- `ExecutionHistory` gains a read-only `get_failures_since` helper.
- No database schema change, no Alembic migration, no new dependency (stdlib `gzip`, `zipfile`, `hashlib`).
- Not changed: `debug.enable_planner_debug` and its `planner_debug` table keep working as today. The maintainer's temporary prod cron and `enable_planner_debug: true` stand-in should be removed by the maintainer once this ships (operational step, not code).

## Capabilities

### New Capabilities
- `planner-run-archive`: per-run archival of planner inputs, plan, diagnostics and errors with retention, plus download and clear from the Debug page.

### Modified Capabilities

None. Existing specs (`durable-schedule-write`, `diagnostics-export`, `database-retention`) keep their requirements; the archive is a separate file store.

## Impact

- Backend: new `backend/services/plan_archive.py`; hooks in `backend/services/planner_service.py`, `planner/pipeline.py`, `planner/output/schedule.py`, `executor/history.py`; endpoints in `backend/api/routers/debug.py`.
- Config: `config.default.yaml`, regenerated `frontend/src/config-help.json`.
- Frontend: `frontend/src/pages/Debug.tsx`, `frontend/src/lib/api.ts`, new component + test.
- Storage: about 10 kB per run, roughly 0.5 MB/day, about 30 MB at the 60-day default. Disk only; lives in `data/` next to `schedule.json`.
- Privacy: archive content is passed through `redact_text` and config secrets are dropped when written, so downloads need no further redaction.
- **Database schema: unchanged (decision: files, see design).**
