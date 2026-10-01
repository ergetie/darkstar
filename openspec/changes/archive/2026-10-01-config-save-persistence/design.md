## Context

The add-on's `run.sh` creates `/app/config.yaml -> /config/darkstar/config.yaml` (and the same for `secrets.yaml`). `/config` is the persistent HA mount. `/app` is the image layer, recreated by the Supervisor on every add-on/HA restart. The backend uses the relative `Path("config.yaml")`, i.e. the symlink.

Current runtime writers (audit, file:line at time of writing):

| Writer | Method | Symlink-safe? | Backup? |
|---|---|---|---|
| `config_migration._write_config` (UI/wizard save via `routers/config.py:328`, `migrate_config`) | temp + `replace(path)` | **No**: replaces the link | yes, but lands in ephemeral `/app/backups` |
| `routers/forecast.py:411-418` reflex toggle | `NamedTemporaryFile` + `replace` | **No**; also EBUSY → 500 on bind mount | no |
| `routers/executor.py:133, 438, 531` | `open("w")` | yes (follows link) | no; non-atomic, violates current spec |
| `routers/theme.py:196` | `open("w")` | yes | no; non-atomic |
| `learning/reflex.py:409` | `open("w")` | yes | no; non-atomic |
| `routers/config.py:1719` reset | `shutil.copy` | yes | no; non-atomic |
| `run.sh` (startup) | `migrate_config` on the real `/config/darkstar/config.yaml`, plus in-place dumps | yes | yes (persistent) |

This explains the user reports: a wizard/Settings save breaks the link. After that the running app reads its private copy, so everything looks fine, and on restart it reverts. Settings written by the in-place writers *before* the link broke survive, which is why only "some things" reset.

Other confirmed defects:
- `_write_config` bind-mount fallback retries the identical `replace` (pointless) before the copy.
- `executor/engine.py:481-545` gates the profile reload on a single `_profile_mtime` that is not tied to a profile name. A switch to a profile whose file shares the previous mtime (Docker COPY) is skipped.
- `frontend/src/App.tsx:40-58` computes `missingProfile` once on mount. `StartupWizard`'s `onComplete` only hides the wizard (`App.tsx:166`), so the "inverter profile not set" banner (`App.tsx:145`) stays until a page reload.
- No test writes through a symlinked config or exercises the EBUSY fallback.

## Goals / Non-Goals

**Goals:**
- Every runtime config write persists to the real file, atomically, durably and serialized, with a backup in a persistent location.
- A write that would not persist is never reported as saved.
- Profile switches always take effect without a restart, and the UI reflects the saved state immediately.

**Non-Goals:**
- Recovering settings already lost (the container was recreated, so the data is gone).
- The onboarding UX redesign (separate change).
- `secrets.yaml` runtime writes (none exist; `run.sh` writes secrets directly on `/config`).
- Moving the app to read `/config/darkstar/config.yaml` directly instead of via the symlink (larger refactor; the symlink stays and is made safe).

## Decisions

1. **One writer: `backend/config_migration.write_config` becomes the only runtime write path.** All writers listed above call it, or a thin `update_config(mutator)` helper built on it. *Alternative:* fix each site individually. Rejected because it duplicates the logic and the drift is exactly what caused this.

2. **Resolve the target with `Path.resolve(strict=False)` before deriving `.tmp`, `.bak` and the backup dir.** The temp file is then a sibling of the real file, so `os.replace` stays on the same filesystem (`/config`), stays atomic, and leaves the symlink intact. *Alternative:* write in place through the link. Rejected because it is not atomic, so a crash can truncate the file.

3. **Durability:** `flush()` + `os.fsync()` the temp file before replace, and fsync the parent directory after replace (best-effort; ignore `OSError` on filesystems that do not support a directory fsync).

4. **Serialization:** a module-level `threading.RLock` guards the entire read-modify-write inside `update_config(mutator)`. Async callers run the critical section via `asyncio.to_thread` so the event loop is not blocked. This is a single process (one uvicorn worker), so an in-process lock is sufficient. *Alternative:* `fcntl` file lock. Not needed for one process; noted as a risk below.

5. **Bind-mount fallback:** on `EBUSY`/`EXDEV`/`ETXTBSY`, skip the identical retry and go straight to the guarded copy: the backup already exists, then fsync the temp file, copy, fsync the target, then post-write verification. The existing restore-from-`.bak`-on-failure behaviour stays.

6. **Add-on persistence guard:** when `SUPERVISOR_TOKEN` is set, the resolved target must be under `/config/darkstar/`. Otherwise the writer logs an error and returns False, and the endpoint returns 500 with a clear message. This prevents any future regression from silently writing to ephemeral storage.

7. **Backup dir:** `_get_persistent_backup_dir` receives the resolved path, so the `/config/darkstar/` prefix check matches and backups go to `/share/darkstar/backups`.

8. **Profile reload:** store `(_profile_name, _profile_mtime)`. Reload when the name differs, or when the name matches but the mtime changed. Set both after the initial load in `__init__`.

9. **Frontend:** extract the config check in `App.tsx` into a callable `refreshConfigState()`. Call it from the wizard's `onComplete` and after a successful Settings save (via the existing config-save success path / an event). Missing-profile is evaluated as `inverter_profile == null` from the freshly fetched config.

## Risks / Trade-offs

- [Several uvicorn workers in the future would bypass the in-process lock] → Document the single-worker assumption in the writer's docstring. An `fcntl` lock can be added later if needed.
- [Callers relying on `open("w")` writing extra keys or formatting] → The callers already load with ruamel. Converting them to `update_config(mutator)` keeps their ruamel round-trip and preserves comments.
- [Guard false positive if a user runs the add-on with a custom path] → The guard applies only when `SUPERVISOR_TOKEN` is set, where `run.sh` always uses `/config/darkstar`.
- [Directory fsync is unsupported on some filesystems] → Best-effort, logged at debug level.
- [Users already affected] → Their settings are already lost; release notes tell them to re-enter them once (release notes are written only on instruction).

## Migration Plan

No data migration. Deploy via a normal add-on update. Rollback: revert the commit. The file format is unchanged.

## Open Questions

- None blocking.
