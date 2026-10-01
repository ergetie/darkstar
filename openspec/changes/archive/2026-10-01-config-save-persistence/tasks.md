## 1. Tests first (reproduce the bug)

- [x] 1.1 Add `tests/config/test_config_write_symlink.py`: a real file plus a symlink in tmp_path. `write_config(symlink)` must leave the link a symlink, update the real file, and create `.tmp`/`.bak` only in the real dir (fails today)
- [x] 1.2 Test: backup dir resolves to the persistent dir for a symlinked `/config/darkstar` target (monkeypatch the prefix/backup root), not `<link dir>/backups`
- [x] 1.3 Test: EBUSY on `replace` (monkeypatched) goes straight to the fsynced copy with no second identical `replace` call; the backup exists before the copy
- [x] 1.4 Test: with `SUPERVISOR_TOKEN` set and the resolved target outside `/config/darkstar/`, the write returns False and the file is unchanged; `POST /api/config/save` returns an error
- [x] 1.5 Test: concurrent `update_config` mutators on different keys both persist
- [x] 1.6 Test: fsync is called on the temp file before replace (spy on `os.fsync`)

## 2. Shared writer (`backend/config_migration.py`)

- [x] 2.1 In `_write_config`, resolve the target (`path.resolve()`) and derive temp, `.bak`, backup dir and verification from the resolved path
- [x] 2.2 Flush and fsync the temp file before replace; best-effort fsync of the parent dir after replace
- [x] 2.3 Replace the duplicate retry in the EBUSY/EXDEV/ETXTBSY branch with the direct guarded copy; keep restore-from-`.bak` on failure and `.tmp` cleanup in `finally`
- [x] 2.4 Add the add-on persistence guard (`SUPERVISOR_TOKEN` set ⇒ resolved target under `/config/darkstar/`, otherwise log an error and return False)
- [x] 2.5 Add a module-level `RLock` and `update_config(path, mutator, strict_validation=...)`, which runs the locked load (ruamel round-trip) → mutate → `_write_config`. Make `write_config` take the same lock. Document the single-worker assumption
- [x] 2.6 Make sure `migrate_config` writes go through the same lock/resolution path

## 3. Route every runtime writer through the shared writer

- [x] 3.1 `backend/api/routers/config.py` save: wrap the read-modify-write in `update_config` (or hold the lock across the load + `write_config`); return an error with a clear message on guard failure
- [x] 3.2 `backend/api/routers/config.py` reset (`shutil.copy` ~L1719): load the defaults and write via the shared writer
- [x] 3.3 `backend/api/routers/forecast.py` reflex toggle (~L391-418): replace NamedTemporaryFile/replace with `update_config`
- [x] 3.4 `backend/api/routers/executor.py` writers (~L133, L438, L531): replace `open("w")` with `update_config`
- [x] 3.5 `backend/api/routers/theme.py` (~L196): replace `open("w")` with `update_config`
- [x] 3.6 `backend/learning/reflex.py` (~L409): replace `open("w")` with `update_config`
- [x] 3.7 Run `rg -n 'config\.yaml' backend executor planner ml` and `rg -n '\.open\("w"|open\(.*"w"|\.replace\(|shutil\.copy' backend executor` to confirm no remaining runtime writer of `config.yaml` bypasses the shared writer; record the result in the PR/commit notes
- [x] 3.8 Async endpoints call the locked writer via `asyncio.to_thread` (no event-loop blocking)
- [x] 3.9 Add or adjust tests for each converted writer (they persist through a symlinked config)

## 4. Executor profile reload (`executor/engine.py`)

- [x] 4.1 Track `_profile_name` with `_profile_mtime`, and set both after the initial load in `__init__`
- [x] 4.2 In `reload_config`, resolve the null/empty profile to `generic` before building the path; reload when the name differs, or when the name matches and the mtime changed
- [x] 4.3 Tests in `tests/executor/test_executor_engine.py`: generic→deye with identical mtimes switches; null reload gives generic without consulting `None.yaml`; same-name mtime change reloads

## 5. Frontend missing-profile state

- [x] 5.1 `frontend/src/App.tsx`: extract the config check into `refreshConfigState()`; call it on mount and from the `StartupWizard` `onComplete`
- [x] 5.2 Re-run `refreshConfigState()` after a successful Settings save (use the existing save-success path; no new global state library)
- [x] 5.3 Frontend test (existing test setup) or manual verification: the banner clears after the wizard and after a Settings profile save without a reload

## 6. Verification

- [x] 6.1 `./scripts/lint.sh` passes (ruff, mypy/pyright, eslint, tests)
- [x] 6.2 Manual add-on-like check: a container/dir setup with `config.yaml` as a symlink into a separate dir; save via UI, restart the process, and settings persist; `ls -la` shows the link intact; the backup is in the persistent dir
- [x] 6.3 Manual standalone Docker check: Settings save and Reflex toggle succeed on the single-file bind mount
- [x] 6.4 Run `openspec validate config-save-persistence --strict`

## Implementation verification notes

- Runtime writer audit: searched `config.yaml` in backend/executor/planner/ml and
  write/replace/copy primitives in backend/executor. All runtime config writes
  now go through `write_config` or `update_config`; startup migration holds the
  same process lock around its complete read/merge/write transaction.
- Manual persistence checks used real Settings-save and Reflex-toggle HTTP
  endpoints in local `python:3.12-slim` containers (no production access).
  Both returned 200 on a real Docker single-file bind mount; a fresh container
  read the saved timezone and Reflex flag successfully.
- The add-on-like container used `/work/config.yaml` as a symlink to
  `/config/darkstar/config.yaml`, with `SUPERVISOR_TOKEN` set. Both saves returned
  200; a fresh process confirmed values persisted and the link remained intact.
  `ls -la` confirmed the symlink; timestamped backups were in the persistent
  `/share/darkstar/backups` mount. HTTP checks exercised the UI save endpoints;
  frontend tests separately exercised wizard and Settings banner refresh.
- Regression tests were added alongside implementation rather than as a
  separately executed red-test phase. Existing EXDEV retry tests were updated
  to assert a single replace attempt followed by the guarded copy.

- Final `./scripts/lint.sh` completed successfully: Ruff lint/format clean,
  Pyright 0 errors/0 warnings, Python 2480 passed (2678 existing warnings),
  frontend format/ESLint/TypeScript clean, frontend 414 passed in 47 files.
- The first full Python run exposed a lenient-migration regression (2479 passed,
  1 failed). Post-write verification now honors `strict_validation=False`, while
  production verification stays strict. All config tests passed (253), and the
  complete lint script was repeated to confirm the corrected final state.
- `openspec validate config-save-persistence --strict` passed.
- Independent verification covered all 31 tasks and 10 requirements. Added a
  pre-replace interruption regression proving partial temporary output leaves
  the live config and symlink intact. Final full checks passed again: Python
  2481 passed (2678 existing warnings), frontend 414 passed in 47 files, and
  Ruff, Pyright, ESLint and TypeScript clean. No remaining verification findings.
