# Design

## Context

See proposal.md. Current state verified 2026-11-21:
- `planner/output/schedule.py::save_schedule_to_json` builds the output dict (`schedule` + `meta`, optional `debug`) and writes `data/schedule.json` atomically; it returns `None`.
- `debug.enable_planner_debug` adds a 30-slot sample (`planner/output/debug.py`) to `schedule.json` and stores it in the `planner_debug` table (`planner/observability/logging.py`), pruned after `learning.planner_debug_retention_days` (default 14).
- The planner service (`backend/services/planner_service.py::_execute`) calls `bin/run_planner.py::main`, which calls `get_all_input_data` and then `PlannerPipeline.generate_schedule`. Typed `PlannerError`s are caught in `_execute`. `_execute` is the one place every run ends, success or failure.
- The pipeline holds `initial_soc_kwh`, the safety floor (`calculate_safety_floor` -> `soc_debug`, `target_soc_kwh`) and `result.status_msg` / `result.time_limit_hit`.
- Executor failures are rows in `execution_log` (`success = 0`, `error_message`), retained 30 days.
- Debug page (`frontend/src/pages/Debug.tsx`) already has download buttons via `lib/download.ts::downloadFile` with busy state and toast on failure, and a clear-logs action.
- Redaction helpers exist in `backend/core/redaction.py` (`redact_text`, `is_secret_key`).

## Goals / Non-Goals

**Goals:** a complete, replayable record per run (success and failure) with bounded disk use; no effect on planning; no DB schema change.

**Non-Goals:** the automatic daily replay job; a replay UI or CLI; browsing records in the UI; archiving runs not started by the planner service (what-if, benchmark, `save_to_file=False`); changing `enable_planner_debug`; archiving executor ticks other than failures.

## Decisions

### D1. Storage: gzip files under `data/plan_archive/`, not the database
- One file per run: `YYYYMMDDTHHMMSSZ-ok.json.gz` or `...-err.json.gz` (UTC start time). Written to a dot-prefixed temp name in the same directory and renamed.
- Why files: no schema change or Alembic migration; ~30 MB at 60 days would otherwise inflate `planner_learning.db`, its backups, the pre-migration backups and every db-snapshot download; DB writes would compete with the recorder/executor on the SQLite writer; a record is self-contained and downloads as-is (no decompress/recompress; zip with `ZIP_STORED`); retention is one `unlink` per old file instead of DELETE + VACUUM; `data/` already holds `schedule.json` and is what the maintainer's stand-in cron writes to, so the format matches what was validated; the archive survives a DB restore/rollback.
- Alternatives: new `plan_archive` table with a gzip BLOB (rejected: schema change, DB bloat, snapshot size); reuse `planner_debug` (rejected: uncompressed text, 30-slot sample, 14-day default, gated on `learning.enable`).
- Trade-off: pruning and summary use file names and mtimes, so listing never decompresses. Counts and sizes come from `os.scandir`.

### D2. Capture model: one writer, in the planner service
- `backend/services/plan_archive.py` exposes a `RunCapture` object and a `ContextVar`. `planner_service._execute` creates a capture before calling `run_planner_main` and calls `plan_archive.write(capture, outcome)` in a `finally`-style path covering success, `PlannerError` and unexpected exceptions.
- `plan_archive.capture(key, value)` is a no-op when no capture is active, so the pipeline can call it unconditionally and CLI/test callers are unaffected.
- Capture points: `bin/run_planner.py` after `get_all_input_data` (`inputs`); `planner/pipeline.py` for `initial_soc_kwh`, `initial_soc_percent`, `safety_floor` (the `soc_debug` dict plus `target_soc_kwh`/`target_soc_pct`), `solver_status` and `time_limit_hit` right after the solve (so a later failure keeps them), and `schedule` (the dict returned by `save_schedule_to_json`) after the save.
- The ContextVar is set in the same asyncio task that runs the pipeline; the solver runs in `to_thread` but capture calls happen on the task side only.

### D3. Record format (`format_version: 1`)
`run_id`, `started_at`, `finished_at`, `outcome` (`ok`|`error`), `planner_version`, `config_version` (the `config_version` key of config.yaml, `null` if absent), `config` (effective config, secret-keyed values removed), `inputs` (the `get_all_input_data` dict), `schedule` (identical to `schedule.json`), `initial_soc_kwh`, `initial_soc_percent`, `safety_floor`, `solver_status`, `time_limit_hit`, `error` (`code`, `message`, `details` or `null`), `executor_errors`, `executor_errors_truncated`.

### D4. Executor errors
At write time, `ExecutionHistory.get_failures_since(iso_ts, limit=50)` returns `execution_log` rows with `success = 0` newer than the previous archived run's `finished_at` (read from the newest archive record; if that cannot be read, the start time in its file name, which can repeat but never lose failures; if there is no record, the last 24 hours). Fields: `executed_at`, `slot_start`, `error_message`. Read-only query on existing columns. Errors that occur after the final run before a download therefore appear in the next record; accepted (no separate event stream).

### D5. Redaction at write time
Config: drop values where `is_secret_key(key)` at any depth. Whole record: serialize to JSON, `redact_text`, then gzip. Doing it once at write time (about 50 runs/day) avoids decompressing months of records on download.

### D6. Retention
`debug.plan_archive_retention_days`, default 60, minimum 7, parsed by a local `_parse_retention` mirroring `backend/db_safety.py::_parse_days` semantics (invalid -> default, below minimum -> minimum). Pruned after every write, using the timestamp parsed from the file name (not mtime, which `rsync`/Syncthing can change). Only names matching the archive regex are deleted. Not added to `db_safety._RULES` because that is database-only.

### D7. API and download
- `GET /api/debug/plan-archive` -> `{enabled, retention_days, count, total_bytes, oldest, newest}`.
- `GET /api/debug/plan-archive/download?days=N` (N optional, 1-365) -> zip in a temp file under `data/plan_archive/` (name `.download-*.zip`), `ZIP_STORED`, plus `manifest.json`; response via `FileResponse` with `BackgroundTask` removal, as in `system.py`. Built in `asyncio.to_thread`. A module-level `asyncio.Lock` returns 409 when busy. Filename `darkstar-plan-archive-<version>-<UTC stamp>.zip`. 404 when no files.
- `DELETE /api/debug/plan-archive` -> `{deleted: n}`. Covered by the existing cross-site write protection.
- All three live in `backend/api/routers/debug.py`; file logic stays in `plan_archive.py`.
- Stale `.tmp`/`.download-*.zip` files older than 1 hour are removed during prune.

### D8. UI
New `PlanArchiveCard` component placed on the Debug page's Logs tab in the right column below "Recent events". Uses `Card`, pill buttons and `Select` from the existing components, `downloadFile` with busy state and error toast (same pattern as the existing Debug downloads), and the `Modal` component for the clear confirmation (not `window.confirm`), with the destructive style from `docs/design-system/AI_GUIDELINES.md`. Colors only via design tokens.

## Risks / Trade-offs

- [Disk growth if runs are far more frequent than ~50/day] -> retention in days bounds it; the summary shows total bytes; the minimum retention is 7 days.
- [Archive write slows the planner] -> serialize, redact and gzip in `asyncio.to_thread`; failures are caught and logged as warnings.
- [Secrets or identifying data in inputs] -> write-time redaction plus secret-key dropping; test asserts both.
- [Record shape drift] -> `format_version` field; replay tooling must check it.
- [Executor errors lag one run] -> documented in the spec scenario; acceptable.
- [Duplicated data with `enable_planner_debug`] -> not removed here; revisit after this ships.

## Migration Plan

No migration. New keys default on; existing installs start archiving after the update. Rollback is deleting `data/plan_archive/`. The maintainer removes the prod cron and `enable_planner_debug: true` stand-in after verifying the first archive files.

## Open Questions

None that change specs, approach or tasks. (Updating `docs/OPERATIONS.md` is gated by the project rule "ask first for `docs/`"; see the follow-up note in tasks.md.)
