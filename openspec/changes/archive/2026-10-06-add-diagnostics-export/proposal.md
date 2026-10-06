## Why

Debugging a user's problem (for example a wrong "Without Darkstar" saving) needs their recorded data, but today the Debug page only offers the log and a config download. A user cannot safely copy `planner_learning.db` while Darkstar runs, because the database is in WAL mode and a plain file copy can be incomplete. Maintainers end up asking users for several manual steps.

## What Changes

- Add a **Download database** button on the Debug page. It returns a consistent snapshot of `planner_learning.db` taken with SQLite's online backup, so Darkstar keeps running and nothing is locked.
- Add an **Export bundle** button on the Debug page. It returns one zip with the files needed to debug: the same consistent database snapshot, `config.yaml` exactly as it is on disk, the log file, `schedule.json`, the JSON output of the health, monitors, status and version endpoints, and a small manifest (Darkstar version, timestamp, what was included or missing).
- The bundle never contains `secrets.yaml`.
- Change the existing `Config` download (`/api/config/download`) to return the raw `config.yaml` file as it is on disk, instead of a rebuilt copy with secrets merged in and then stripped. The `Logs` download stays unchanged.

## Capabilities

### New Capabilities
- `diagnostics-export`: Downloading a consistent database snapshot and a diagnostics zip bundle from the Debug page.

### Modified Capabilities

## Impact

- Backend: new endpoints for the database snapshot and the bundle, in `backend/api/routers/system.py` (or a new router) and the existing `LearningStore` for the DB path.
- Frontend: two new buttons in `frontend/src/pages/Debug.tsx` next to Logs and Config; an API helper in `frontend/src/lib/api.ts` if needed.
- No schema changes, no new dependencies (SQLite backup and zip are in the Python standard library).
- Docs: `docs/` is not touched without your OK.
