## Why

`config.yaml` grows on every config write because the template's comment block for a list key is duplicated each time (GitHub issue #4). The trigger is a non-empty `executor.excess_pv.priority`: each write adds about 840 B. Prod currently holds 22 copies (49.8 kB). The growth is unbounded and makes the file harder to read and slower to write.

## What Changes

- `template_aware_merge` uses only the user config's values. Comments carried in the user's YAML tree no longer enter the merged output. All comments come from the template, exactly once.
- Configs that are already bloated shrink back to normal on the next write (UI save or add-on start).
- Add a regression test that runs repeated write cycles against the real `config.default.yaml` and asserts the output size stays stable.

## Capabilities

### New Capabilities

### Modified Capabilities
- `config-migration`: adds a requirement that repeated template merges are size-stable and comments come only from the template.

## Impact

- Code: `backend/config_migration.py` (`template_aware_merge`). Both callers are covered with no change: `POST /api/config/save` (`backend/api/routers/config.py`) and startup `migrate_config`.
- Tests: `tests/config/test_config_migration.py`.
- User-visible: comments a user typed into `config.yaml` by hand don't survive a write. Template comments and all values are kept.
- No new dependencies, no schema change.
