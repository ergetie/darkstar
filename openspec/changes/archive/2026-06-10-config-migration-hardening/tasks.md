## 1. Bind-mount fallback atomicity (#32)

- [x] 1.1 In `_write_config` (`backend/config_migration.py:879-927`), confirm the `.tmp` file is created in the target's own directory (it is, via `path.with_name(...)`); document/keep this invariant
- [x] 1.2 Change the `OSError` (`EBUSY`/`EXDEV`/`ETXTBSY`) branch (`:908-916`) to retry `os.replace`/`temp_path.replace(path)` within the mounted directory instead of `shutil.copy2` as the primary action
- [x] 1.3 Keep `shutil.copy2` only as a guarded last resort: add an `fsync` of the temp file before the copy and of the target after, plus a warning log when this last-resort path is taken
- [x] 1.4 Verify the restore-on-failure path and `.tmp` cleanup in the `finally` block still behave correctly after the change

## 2. Explicit config_version migration step (#33)

- [x] 2.1 Define a single `CURRENT_CONFIG_VERSION = 2` constant in `backend/config_migration.py` (replace any magic literals where reasonable)
- [x] 2.2 Add a migration step in `migrate_config()` that sets `config_version` to `CURRENT_CONFIG_VERSION` when missing or lower; never downgrade a higher value
- [x] 2.3 Make the step mark `pre_merge_changes = True` so the write fires even when the template merge is skipped (default template missing `:782-786`, unreadable `:797-801`, or merge path)
- [x] 2.4 Place the step so a clean already-v2 config still produces no write (preserve idempotency); verify against the existing "fully-migrated configs are not modified" requirement

## 3. UI save through the atomic writer (#31)

- [x] 3.1 In `backend/api/routers/config.py`, import `_write_config` from `backend.config_migration` (router already imports from that module)
- [x] 3.2 Replace the inline `config_path.open("w")` + `yaml_handler.dump(data, f)` (`:301-302`) with a `_write_config(config_path, data, yaml_handler, ...)` call
- [x] 3.3 After the call, verify the on-disk config is non-empty/valid; if the write was aborted (validation failure inside `_write_config`), return an error from the endpoint instead of a success status
- [x] 3.4 Confirm the existing post-save steps (executor `reload_config`, planner `clear_retry_suspension`, warnings passthrough) still run unchanged on success

## 4. Tests

- [x] 4.1 Test: UI save routes through the atomic writer — interrupting before the replace leaves the prior `config.yaml` intact (no truncation)
- [x] 4.2 Test: UI save creates a timestamped backup before overwriting
- [x] 4.3 Test: an aborted/invalid UI save returns an error, not success, and does not truncate the file
- [x] 4.4 Test: bind-mount (`EXDEV`) path completes via atomic replace within the same filesystem, not a streaming copy
- [x] 4.5 Test: `migrate_config()` sets `config_version: 2` when missing even with the template merge skipped (no default template present)
- [x] 4.6 Test: `config_version` is not downgraded when already higher than current
- [x] 4.7 Test: a clean already-v2 config produces no file write (idempotency regression guard)

## 5. Validation

- [x] 5.1 Run `openspec validate config-migration-hardening` and resolve any issues
- [x] 5.2 Run the full test suite; confirm no regressions against the 1051-test baseline
