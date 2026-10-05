## 1. Regression tests (write first, confirm they fail on main)

- [x] 1.1 In `tests/config/test_config_migration.py`, add a test that builds a user config from the real `config.default.yaml` with a non-empty `executor.excess_pv.priority` (written as text), runs 5 merge+dump cycles, and asserts identical output and a single copy of the excess_pv example comment block
- [x] 1.2 Add a self-heal test: a user config with duplicated comment blocks shrinks to a single copy after one merge, with values unchanged
- [x] 1.3 Add a test that quoted strings and list values survive the merge unchanged
- [x] 1.4 Run the new tests and confirm 1.1 and 1.2 fail on current code

## 2. Fix

- [x] 2.1 In `backend/config_migration.py`, add a small recursive helper that converts mappings to `dict` and sequences to `list`, returning scalars unchanged
- [x] 2.2 Call it on `user_cfg` at the start of `template_aware_merge`, before `recursive_merge`, and update the docstring

## 3. Verify

- [x] 3.1 Run the new tests and confirm they pass
- [x] 3.2 Run the full `tests/config/` suite
- [x] 3.3 Run `./scripts/lint.sh`
- [x] 3.4 Re-run the scratch repro against the real template (no growth), and against a copy of the prod config (shrinks to one copy, values identical)
