## Context

The Debug page (`frontend/src/pages/Debug.tsx`) has two download buttons today: `api/system/logs` (`FileResponse` of `data/darkstar.log`) and `api/config/download` (a copy of `config.yaml` with secrets merged in and then stripped). There is no way to get the database.

`planner_learning.db` runs in WAL mode (`LearningStore.ensure_wal_mode`, spec `database-concurrency-safety`). Recent writes live in the `-wal` file, so copying only the `.db` file while Darkstar runs can give an incomplete or unreadable copy. The DB path is `store.db_path` (config `learning.sqlite_path`, default `data/planner_learning.db`), and the store is available to routes through `get_learning_store`.

Other files already live in known places: `config.yaml` in the working directory, `data/darkstar.log`, `data/schedule.json`. Debug information is already exposed by `/api/version`, `/api/status`, `/api/system/health` and `/api/system/monitors`.

The database and `config.yaml` contain no secrets. Only `secrets.yaml` does, and it is never read by this feature.

## Goals / Non-Goals

**Goals:**
- Download a consistent DB snapshot while Darkstar keeps running, without locking or stalling other requests.
- Download one zip with everything a maintainer normally asks for, from one click.
- Include `config.yaml` exactly as on disk.

**Non-Goals:**
- No import or restore of a database or bundle.
- No change to the existing Logs download. The plain `GET /api/config` (sanitized JSON for the UI) is also untouched.
- No scheduled or automatic backups.

## Decisions

**1. Snapshot with SQLite's online backup API (`sqlite3.Connection.backup`).**
The source is opened read-only (`file:<path>?mode=ro`, `uri=True`) and copied page by page into a temporary file, which is then streamed as the response and deleted afterwards. The backup yields a transactionally consistent copy while the app writes. Alternatives: `VACUUM INTO` (also consistent, but rewrites the whole file and holds a read transaction for longer), copying `.db` plus `-wal` (race-prone), or a checkpoint then copy (still racy and blocks writers). The temporary file goes in the data directory so it is on the same volume as the DB.

**2. The backup runs in a worker thread.**
`sqlite3` is synchronous and the copy of a large DB takes time. The route runs it with `asyncio.to_thread`, in line with the "synchronous database reads do not block the event loop" requirement in `database-concurrency-safety`. The backup uses the standard-library `sqlite3` module with a generous busy timeout, separate from the async engine, so the shared engine and its pool are untouched.

**3. The bundle is assembled with `zipfile` into a temporary file.**
Each item is added independently. If an item is missing or fails (for example `schedule.json` does not exist yet, or Home Assistant is unreachable for `/api/status`), the bundle is still returned and the manifest lists that item with the reason. A debug export must work precisely when the system is unhealthy.

**4. Bundle contents (fixed list).**
`planner_learning.db` (the same consistent snapshot as decision 1, produced by one shared helper), `config.yaml` (raw file bytes), `darkstar.log`, `schedule.json`, `version.json`, `status.json`, `health.json`, `monitors.json`, `manifest.json`. The JSON items come from calling the existing handler functions directly, not over HTTP. `manifest.json` records the Darkstar version, the export time (UTC) and, per item, `included` or the error text. `secrets.yaml` is not in the list and no code path reads it.

**5. Two endpoints, both GET, next to the existing download endpoints.**
`/api/system/db-snapshot` and `/api/system/diagnostics`, in `backend/api/routers/system.py`. Both return `FileResponse` with a `BackgroundTask` that deletes the temporary file. File names carry a UTC timestamp and the version (for example `darkstar-diagnostics-<version>-<yyyymmdd-hhmmss>.zip`, `planner_learning-<yyyymmdd-hhmmss>.db`) so several exports from the same user do not collide in a Discord thread.

**6. `/api/config/download` returns the raw file.**
Today it loads the YAML, merges in the Home Assistant and notification secrets from `secrets.yaml`, removes them again and re-serializes. With the raw file there is nothing to merge or strip, so the handler serves `config.yaml` bytes as they are (`FileResponse`, `application/x-yaml`, same download name as today). The bundle and the Config button therefore export the identical content, and the code that reads `secrets.yaml` for the download goes away.

**7. Two new buttons in `Debug.tsx`** ("Database" and "Export bundle"), styled like Logs and Config. Both use a small fetch-to-blob helper (`frontend/src/lib/download.ts`) with a relative URL (`api/...`, which keeps working behind Home Assistant ingress) instead of `window.location.href`, because a navigation gives no signal when the slow download has finished. While a download runs the clicked button shows a `Loader2` spinner and a label ("Preparing…" / "Exporting…"), both buttons are disabled, and a ref guard blocks double clicks. Failures (network, HTTP error detail from the backend, and 409 mapped to "Another export is already running…") are shown with the existing `useToast` error toast. The file name comes from `Content-Disposition`. Logs and Config keep the plain navigation. The toolbar uses `flex-wrap` with `gap-2` and every button `whitespace-nowrap`, so it wraps onto extra rows instead of squeezing labels.

## Risks / Trade-offs

- [Large DB makes the snapshot slow or fills the disk] → The temp file is written in the data directory and deleted after the response; the snapshot is skipped with HTTP 507/500 and a clear message if the copy fails. The size is already visible via `/api/system/health`.
- [Concurrent exports pile up on a small device] → One shared lock for the snapshot and the bundle, since both run the DB backup; a second request while one runs returns HTTP 409.
- [Backup copy is momentarily slower while the recorder writes] → The backup retries on busy pages in small steps; the app's own writes are not blocked because the source connection is read-only and WAL readers do not block writers.
- [Log file may be large] → It is added as-is; zip compression keeps the bundle small.
- [Exposes data to anyone who can reach the UI] → The endpoints sit behind the same access as the rest of the API, like the existing log and config downloads. This feature adds no new authentication.
