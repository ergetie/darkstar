# Tasks

## 1. Build plumbing

- [x] 1.1 Add `DARKSTAR_VERSION` and `DARKSTAR_RELEASE_CHANNEL` build args to `Dockerfile` (default channel stays `stable`)
- [x] 1.2 Add `build.args`, (opt-in via compose profile `updater`, `${VAR:-}` defaults) `DARKSTAR_UPDATER_URL`, `DARKSTAR_UPDATER_TOKEN` env and the `updater` service (socket, repo at identical path, `./data` read-only, state volume, no published port) to `docker-compose.yml`
- [x] 1.3 Create `updater/Dockerfile` (python:3.12-slim, git, docker CLI + compose plugin) and entrypoint that refuses an empty token

## 2. Updater service (pure logic, injectable runners)

- [x] 2.1 Git helpers: fetch, resolve channel target (dev/stable), dirty-tree check, commit subjects, version string
- [x] 2.2 Alembic gate: read DB revision (sqlite ro) and revision set at target ref
- [x] 2.3 State store (channel default from `VERSION`, last check, last apply) in the state volume
- [x] 2.4 Apply runner: single-flight lock, gates, checkout, build with args, restore on failure, `up -d --no-deps darkstar`, health wait, log file
- [x] 2.5 HTTP server: bearer auth (constant-time), fixed routes status/check/channel/apply/log, 6 h background check, manual check rate limit

## 3. Darkstar backend

- [x] 3.1 Updater client (aiohttp, 5 s timeout) and `backend/api/routers/updater.py` proxy endpoints, 404 unless installation type is `docker` and URL configured, "unavailable" state on connection errors
- [x] 3.2 Register router in `backend/main.py`; reflect active channel in `classify_release_channel` data (via build arg ENV, no code change expected, verify)
- [x] 3.3 Optionally expose `commit` in `/api/version`

## 4. Frontend

- [x] 4.1 Agree exact UI layout with the user before building
- [x] 4.2 API client and hooks for status, check, channel, apply, incremental log
- [x] 4.3 Version dot in sidebar + mobile nav, floating update card opened from the version, dismissible update banner (dismissal stored per target version), per `docs/design-system/AI_GUIDELINES.md`: channel selector, check now, update confirm, blocked/dirty/unavailable messages, live log, restarting + reconnect

## 5. Tests

- [x] 5.1 Updater unit tests with fake git/docker runners and local temp git repos: channels, update available, dirty tree, alembic gate (dev to stable block), build failure restores checkout, single-flight, auth 401, ref injection ignored
- [x] 5.2 Backend router tests with a fake updater client (hidden for ha_addon, unavailable state, proxying)
- [x] 5.3 Frontend tests with mocked API (states, confirm, reconnect polling)
- [x] 5.4 Ensure no test touches network, GitHub or Docker

## 6. Verification and docs

- [x] 6.1 Run `./scripts/lint.sh` and the full test suite
- [x] 6.2 Manual end-to-end on a docker install (dev update, stable block, forced build failure) — deferred: run on prod after push (user decision)
- [x] 6.3 With user approval, update docs/OPERATIONS.md (migration steps, token setup, security note)
