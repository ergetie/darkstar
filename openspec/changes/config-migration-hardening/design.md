## Context

`config.yaml` is the single source of truth for Darkstar. Two code paths write it:

1. **Startup migration** — `migrate_config()` (`backend/config_migration.py:697`) calls the atomic helper `_write_config()` (`:879`), which creates a timestamped backup, writes a `.tmp` sibling, then `os.replace`s it into place.
2. **UI save** — `POST /api/config` (`backend/api/routers/config.py:301-302`) opens the live file in `"w"` mode and dumps directly — **no temp file, no backup**.

Three stabilization-review findings converge here:
- **#31 (S2):** the UI save path truncates-in-place; a crash/disk-full mid-write loses the config with no recovery point — even though `_write_config` is one import away (the router already imports from `config_migration`).
- **#32 (S3):** inside `_write_config`, the Docker bind-mount fallback (`:908-916`) degrades to `shutil.copy2(temp_path, path)` — a non-atomic truncate-then-stream copy, re-introducing the exact partial-write risk the atomic rename exists to prevent.
- **#33 (S3):** `config_version` is never written by migration (grep confirms only positional validation at `:523-528`); it arrives solely via the template merge. If the merge is skipped — default template missing (`:782-786`) or user config fails structure validation (`:740-744`) — `config_version` stays `< 2` and the ARC15 entity arrays are silently ignored by consumers (`loads/service.py:33`, `api/routers/config.py:347`, `planner/solver/adapter.py:27-29`).

Constraint: this is a hardening change — a successful save/migration must produce the **same** file content as today. Only the failure modes and the `config_version` field change.

## Goals / Non-Goals

**Goals:**
- Every writer of `config.yaml` persists atomically (temp-then-rename) with a pre-overwrite backup, leaving no path that can truncate the live file.
- The bind-mount fallback stays atomic by keeping the temp file on the same filesystem as the target.
- `config_version` is set explicitly by migration, independent of the template merge.

**Non-Goals:**
- No config schema change; no new config keys.
- No change to validation rules, the executor-reload, or planner-retry-clear steps that follow a UI save.
- Finding #30 (legacy `deferrable_loads` → arrays conversion) — `wontfix`, out of scope.
- No change to the migration's field-migration steps or deprecated-key sweep.

## Decisions

### D1 — Route the UI save through `_write_config` rather than duplicating atomic logic
The router save handler will call `_write_config(config_path, data, yaml_handler, strict_validation=...)` instead of the inline `open("w")` + `dump`. **Why over replicating temp+rename in the router:** one audited atomic writer is lower-risk than two; `_write_config` already does backup + post-write verification + restore-on-failure, and the router already imports from `config_migration`. Alternative considered — extract a new shared util — rejected as unnecessary churn; `_write_config` is already the de-facto shared writer.
- Note: `_write_config` returns `None` and logs+aborts on validation failure. The router already runs its own `_validate_config_for_save` (blocking on errors) before writing, so the save path keeps its existing 400-on-error behaviour; `_write_config`'s internal validation is a backstop. Confirm the post-write file is non-empty so the endpoint still reports failure if the write was aborted.

### D2 — Bind-mount fallback writes the temp file inside the target directory, then `os.replace`
The `EXDEV` failure means the `.tmp` sibling and the target are on different filesystems. Fix: create the temp file in the **same directory as the target** (it already is — `path.with_name(...)`), and on the cross-device branch, retry `os.replace` within the mount instead of `shutil.copy2`. If `os.replace` genuinely cannot work on that mount, fall back to `copy2` **only as a last resort** and `fsync` before/after so a partial copy is at least flushed — but the primary path must be an atomic rename within the mounted directory. **Why:** `os.replace` is atomic only within one filesystem; keeping temp + target co-located removes the `EXDEV` trigger entirely for the common bind-mount layout.

### D3 — Add an explicit `config_version` migration step before `remove_deprecated_keys`/write
A small step in `migrate_config()` sets `config["config_version"] = CURRENT_CONFIG_VERSION` (2) when it is missing or `< 2`, marking `pre_merge_changes = True` so the write fires even when the template merge is skipped. **Why a dedicated step over relying on the template:** the template merge is the *only* current source and it has two documented skip paths; an explicit assignment is the single guaranteed point. The version constant should be defined once in the module (not a magic literal). This must not *downgrade* a higher version, and must run such that a clean already-v2 config still writes nothing (idempotency preserved).

## Risks / Trade-offs

- **[UI save now creates a backup on every save]** → This is already migration behaviour, pruned to 30 timestamped backups (`create_timestamped_backup`, `max_backups=30`). Acceptable; matches existing semantics.
- **[`_write_config` silently aborts on validation failure (returns None)]** → Router must verify the on-disk result and surface a 500/400 if the write did not happen, so saves don't appear to succeed silently. Covered by a spec scenario.
- **[Bind-mount `os.replace` retry could still hit EXDEV on exotic mounts]** → last-resort `copy2` + `fsync` retained as a guarded fallback with a warning log; backup still exists for recovery.
- **[Setting `config_version` could mask a genuinely-unmigrated config]** → the step only sets the field; it does not fabricate ARC15 arrays. A config whose arrays are truly empty is a separate concern (#30, wontfix) and unaffected.

## Migration Plan

No data migration. Deploy is code-only. Rollback = revert the change; existing configs are untouched (backups from the new UI-save path remain valid and readable). On first startup after deploy, configs missing `config_version` get it written once (idempotent thereafter).

## Open Questions

- None blocking. The `CURRENT_CONFIG_VERSION` constant value (2) is taken from existing consumer gates (`>= 2`); if a future schema bump lands, this step becomes the canonical place to raise it.
