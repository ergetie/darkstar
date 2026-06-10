## Why

The `config.yaml` file is Darkstar's source of truth, but two write paths can leave it truncated or empty with no recovery point, and one migration gap can silently disable the ARC15 entity-centric config. These are the three config-durability findings from the stabilization review (#31 S2, #32 S3, #33 S3): a crash or full disk at the wrong moment loses the user's whole configuration.

## What Changes

- **UI "Save Configuration" becomes crash-safe (#31).** The `POST /api/config` save handler currently opens the live `config.yaml` in `"w"` mode (immediate truncate) and dumps directly — no temp file, no backup. It will instead route through the existing atomic, backup-creating `_write_config` helper that migration already uses.
- **The bind-mount fallback becomes atomic (#32).** When `os.replace` fails across devices (Docker bind mounts), `_write_config` currently degrades to a non-atomic `shutil.copy2(temp, path)` — a truncate-then-stream copy that a mid-write crash can leave partial. It will instead write the temp file *inside the same mounted directory* and `os.replace` within that filesystem, so the swap stays atomic.
- **Migration explicitly sets `config_version` (#33).** Nothing in `migrate_config()` ever writes `config_version`; today it only arrives via the template merge. If the merge is skipped (default template missing, or user config fails structure validation), `config_version` is never bumped to `2`, so the planner/executor/loads silently ignore the ARC15 entity arrays (they gate on `>= 2`). A dedicated migration step will set it independently of the template merge.

## Capabilities

### New Capabilities
- `durable-config-write`: the shared contract that **every** writer of `config.yaml` (startup migration and the UI save endpoint) MUST persist atomically and never leave a truncated/empty file — temp-file-then-atomic-rename within the same filesystem, plus a backup before overwrite, including on Docker bind mounts.

### Modified Capabilities
- `config-migration`: add a requirement that `migrate_config()` explicitly sets `config_version` to the current schema version, independent of whether the template merge runs.

## Impact

- **Code:** `backend/api/routers/config.py` (route save through `_write_config`); `backend/config_migration.py` (`_write_config` bind-mount fallback; new `config_version` migration step).
- **Behaviour:** no change to a successful save's result; only the failure modes change (partial/empty files become unreachable, ARC15 arrays stop silently disabling). No config schema change.
- **Risk:** the UI save now creates timestamped backups on every save (existing migration behaviour, already pruned to 30); the executor-reload / planner-retry-clear steps that follow the save are unaffected.
- **Out of scope:** Finding #30 (legacy `deferrable_loads` conversion) is `wontfix` and not part of this change.
