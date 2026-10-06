## 1. Database snapshot endpoint

- [x] 1.1 Add `GET /api/system/db-snapshot` in `backend/api/routers/system.py`: resolve the DB path from `get_learning_store`, return 404 if the file is missing
- [x] 1.2 Take the snapshot with `sqlite3` online backup from a read-only source connection into a temporary file in the data directory, run via `asyncio.to_thread`
- [x] 1.3 Stream the file with a timestamped name and delete the temporary file afterwards, including on failure
- [x] 1.4 Put the snapshot in one shared helper used by both the standalone endpoint and the bundle, behind one lock; reject a second concurrent snapshot or bundle with HTTP 409

## 2. Diagnostics bundle endpoint

- [x] 2.1 Add `GET /api/system/diagnostics` that builds a zip in a temporary file with `zipfile`
- [x] 2.2 Add the database snapshot from the shared helper as `planner_learning.db`, `config.yaml` as raw bytes, `data/darkstar.log` and `data/schedule.json`; never read `secrets.yaml`
- [x] 2.3 Add `version.json`, `status.json`, `health.json` and `monitors.json` by calling the existing handlers directly
- [x] 2.4 Make every item fail independently and record the result per item in `manifest.json` (version, UTC export time, included or error)
- [x] 2.5 Return the zip with a timestamped and versioned name and delete the temporary files afterwards

## 3. Debug page buttons

- [x] 3.1 Add Database and Export bundle buttons in `frontend/src/pages/Debug.tsx` beside Logs and Config, using relative URLs, following `docs/design-system/AI_GUIDELINES.md`
- [x] 3.1a Make the toolbar wrap onto further rows (`flex-wrap`) and keep button text on one line (`whitespace-nowrap`)
- [x] 3.1b Download Database and Export bundle with fetch-to-blob (`frontend/src/lib/download.ts`); show a spinner and a disabled button ("Preparing…" / "Exporting…") from click until the file is delivered or failed, block double clicks, and show failures (including the 409) as an error toast
- [x] 3.2 Change `/api/config/download` in `backend/api/routers/config.py` to serve the raw `config.yaml` file (404 if missing) and remove the secrets merge and strip code from it; leave the Logs button and `GET /api/config` unchanged
- [x] 3.3 Test that the config download is byte-identical to the file on disk and does not read `secrets.yaml`

## 4. Tests

- [x] 4.1 Snapshot test: result opens, passes `PRAGMA integrity_check`, contains rows written to the WAL, and the live DB is unchanged
- [x] 4.2 Snapshot test: missing DB gives an error and no leftover temp file; concurrent request gives 409
- [x] 4.3 Bundle test: expected files present including a `planner_learning.db` that passes `PRAGMA integrity_check`, `config.yaml` byte-identical, no secrets file
- [x] 4.4 Bundle test: a missing `schedule.json` or a failing status call still returns a zip with the reason in `manifest.json`
- [x] 4.5 Frontend test (`Debug.downloads.test.tsx`): Export bundle label, toolbar wrapping classes, busy state and double-click guard for both buttons, error toast on 409, HTTP error and network failure, Config button URL

## 5. Verification

- [x] 5.1 Run `./scripts/lint.sh` and the new tests
- [x] 5.2 Manually download both files from a running dev instance and open the snapshot with Python's `sqlite3`
