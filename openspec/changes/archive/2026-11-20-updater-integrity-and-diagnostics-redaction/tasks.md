# Tasks

Run single tests with `UV_NO_SYNC=1 uv run python -m pytest <path> -v`. Updater tests live in `tests/updater/`, bundle tests in `tests/api/test_diagnostics_export.py`. Do not stage or commit. Editing `docs/OPERATIONS.md` is approved.

## 1. Updater origin pin and fetch hardening

- [x] 1.1 In `updater/repo.py` add origin normalisation and `Repo.assert_origin()` (https, `git@github.com:`, `ssh://git@github.com/`, with or without `.git`, must equal `ergetie/darkstar`); add `tests/updater/test_repo_pin.py` for accepted forms and a foreign host/owner raising `GitError`; verify the file passes.
- [x] 1.2 Call `assert_origin()` before fetch and in `begin_apply`; change fetch to `fetch --prune origin` plus `--tags` without `--force`/`--prune-tags`; treat only a "would clobber existing tag" rejection as a non-fatal warning stored in `last_check.warnings`; tests: foreign origin gives a check error and no fetch call, moved tag keeps the local tag and succeeds with a warning, deleted upstream tag stays local, other fetch failure is still an error; verify with `tests/updater/`.
- [x] 1.3 In `updater/service.py` install by commit hash (stable `checkout --detach <plan.commit>`, dev `merge --ff-only <plan.commit>`); refuse a dev target when HEAD is not an ancestor ("Dev branch history diverged, refusing non-fast-forward update") and a stable detached target that is a strict ancestor of HEAD ("Target is older than the installed version"), leaving dev-to-stable switching allowed; tests for each rejection, for hash checkout after the tag moved, and for the dev-to-stable switch; verify with `tests/updater/test_updater.py`.
- [x] 1.4 Document the pinned origin, tag handling (clobber warning) and the dev fast-forward / stable no-downgrade rules in the updater section of `docs/OPERATIONS.md`, including the recovery for a non-ergetie origin (`git remote set-url origin https://github.com/ergetie/darkstar.git`); verify the command runs as written in a scratch repo.

## 2. Redaction functions

- [x] 2.1 Create `backend/core/redaction.py` with `redact_text()` (reusing `scrub_urls`/`mask_secret_params`; host allowlist and private/local rules; public IPv4; lat/lon patterns) per design D5; tests in `tests/core/test_redaction.py` for nabu.casa/DDNS host, kept private IP and `homeassistant`, allowlisted service hosts, public IP, JSON-escaped log lines, coordinates, `token=`, bearer; verify passes.
- [x] 2.2 Add `redact_config()` (ruamel round-trip, secret-named keys at any depth, empty values kept, lat/lon rounded to one decimal, string values through `redact_text`, raises `RedactionError` on parse failure); tests that comments and key order survive, a config with nothing to redact is byte-identical, entity ids survive, and `config.default.yaml` redacts without error; verify passes.
- [x] 2.3 Add `mask_config_versions(db_copy_path)` that rewrites only `config_versions.yaml_blob` on the snapshot copy with the secret-key rule (unparseable blob replaced by a placeholder); tests that a secret is gone from the copy's rows, a non-secret value and every other table are unchanged, and `PRAGMA integrity_check` is `ok`; verify passes.

## 3. Bundle integration

- [x] 3.1 In `backend/api/routers/system.py` pass `darkstar.log`, `darkstar.log.1` (line by line), `schedule.json` and all JSON payloads through `redact_text` and `config.yaml` through `redact_config` (omit with `error: could not redact config` on failure); add `redacted: true` to the manifest; update the affected tests in `tests/api/test_diagnostics_export.py` (config now redacted rather than byte-identical when it has items to redact) and add tests for log/schedule/status redaction and the unparseable config case; verify passes.
- [x] 3.2 Apply `mask_config_versions` to the bundle snapshot copy before zipping, fail closed (on a masking error omit the database and record `error: could not mask config versions` in the manifest; the standalone `/api/system/db-snapshot` stays raw); update the endpoint description text; tests that the bundle DB has no secret in `config_versions`, other tables equal the live DB, the standalone snapshot is unchanged, and a masking failure omits the database; verify passes.
- [x] 3.3 Redact the `/api/system/logs` download with `redact_text` (temporary file removed afterwards); keep `/api/config/download` raw; tests for both; verify passes.
- [x] 3.4 Document in `docs/OPERATIONS.md` what the bundle redacts and what it keeps (entity ids, parameters, private HA address, database always included with masked config-version secrets, coordinates rounded in config only); verify against the behaviour covered by the tests in 3.1 and 3.2.

## 4. Integration checks

- [x] 4.1 Run `./scripts/lint.sh` and `UV_NO_SYNC=1 uv run python -m pytest tests/updater tests/core/test_redaction.py tests/api/test_diagnostics_export.py -q`; both must pass with no new warnings.

## Workflow follow-up

- Archive the change after review.
