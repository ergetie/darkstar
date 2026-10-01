## Why

In the Home Assistant add-on, settings saved from the UI (Settings page, startup wizard, Reflex toggle) are lost on every add-on/HA restart. Multiple users have reported it (inverter profile, entities, EV tab, transfer fees/taxes reset). The add-on exposes `/app/config.yaml` as a symlink to the persistent `/config/darkstar/config.yaml`; the atomic writer renames its temp file onto the *symlink path*, replacing the link with a regular file in the ephemeral container filesystem. The running app sees the new values, the persistent file never changes, and the next start re-links to the stale file. The only working workaround today is hand-editing the file in HA's File Editor.

## What Changes

- Single config writer: every runtime write of `config.yaml` goes through one atomic, durable, serialized helper. This covers Settings/wizard save, Reflex toggle, executor endpoints, theme, Reflex learning engine and config reset.
- The writer resolves symlinks to the real target before writing. The temp file, the atomic replace and the `.bak` all happen in the real file's directory, so the symlink is never replaced.
- Durable writes: fsync the temp file before replace and fsync the directory after.
- Writes are serialized with a process-wide lock covering the full read-modify-write. This stops concurrent writers (e.g. a UI save plus the nightly Reflex write) from losing each other's changes.
- Bind-mount fallback fixed: the redundant identical retry is removed. On `EBUSY`/`EXDEV`/`ETXTBSY` (standalone Docker single-file bind mount) the writer goes straight to the guarded, fsynced in-place copy with a backup already taken. The Reflex toggle no longer 500s in standalone Docker.
- Timestamped backups resolve against the real path. In the add-on they land in persistent `/share/darkstar/backups` instead of the ephemeral `/app/backups`.
- Write-target guard: when running as the add-on (`SUPERVISOR_TOKEN` set), the writer verifies that the resolved target is under `/config/darkstar/`. If it is not, the writer refuses to save and returns an error, so the UI never again says "saved" for an ephemeral write. Settings already lost to the bug cannot be recovered, because the Supervisor recreates the container on restart. Affected users re-enter their settings once after upgrading.
- Executor profile reload: the reload is keyed on (profile name, profile file mtime) instead of mtime alone. Switching profiles can therefore never be skipped because two profile files share an mtime (common in Docker images).
- Frontend: the "inverter profile not set" banner is re-evaluated after the wizard completes (and after saves) instead of only on page mount.
- Tests for all of the above, including writing through a symlinked config and the bind-mount fallback.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `durable-config-write`: the requirements now cover all writers (not just migration + UI save), symlink-safe targets, durability (fsync), serialized read-modify-write, a corrected bind-mount fallback, backup location resolved from the real path, and an add-on persistent-target guard.
- `executor`: profile reload must apply on any profile name change regardless of file mtimes.
- `startup-wizard`: the missing-profile state must clear once the wizard saves a profile, with no stale warning.

## Impact

- Backend: `backend/config_migration.py` (`_write_config`, `write_config`, backup dir resolution), `backend/api/routers/config.py` (save, reset), `backend/api/routers/forecast.py` (reflex toggle), `backend/api/routers/executor.py` (3 writers), `backend/api/routers/theme.py`, `backend/learning/reflex.py`.
- Executor: `executor/engine.py` `reload_config`.
- Frontend: `frontend/src/App.tsx` (banner state), `StartupWizard` completion callback.
- Tests: `tests/config/*`, `tests/executor/test_executor_engine.py`, new symlink/bind-mount write tests.
- No API shape changes, no new dependencies, no DB changes.
