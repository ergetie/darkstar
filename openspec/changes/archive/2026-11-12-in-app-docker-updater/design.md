# Design

## Context

- `docker-compose.yml` has one `darkstar` service (`build: .`, bind mounts `config.yaml`, `secrets.yaml`, `data/`, `backups/`). `.dockerignore` excludes `.git`, so the container cannot run git; version comes from `DARKSTAR_VERSION` env, then the baked `VERSION` file (`dev-YYMMDD.HHMM` on dev, committed by CI), see `backend/core/version.py`.
- `Dockerfile` hard-codes `ENV DARKSTAR_RELEASE_CHANNEL=stable`; `classify_release_channel()` (installation stats) reads it. A locally built dev install would wrongly report `stable`.
- `scripts/docker-entrypoint.sh` runs `alembic upgrade head` and exits 1 on failure; code lacking the DB's revision crash-loops. Migrations live in `alembic/versions/`; DB at `/data/planner_learning.db` (host `./data`).
- Tags look like `v2.7.1-beta`. System router: `backend/api/routers/system.py` (`/api/version`); Settings UI: `frontend/src/pages/settings/SystemTab.tsx`.

## Goals / Non-Goals

**Goals:** UI check/apply for docker installs; local build from git; dev/stable channels; no socket in Darkstar; safe gates.
**Non-Goals:** GHCR/CI changes; HA add-on updates; pre-update backup; automatic downgrade; updating the updater itself from the UI; auto-apply of updates.

## Decisions

1. **Sidecar container, not host service.** A compose service `updater` (image built from `updater/Dockerfile`: python:3.12-slim + git + docker CLI + compose plugin) with `/var/run/docker.sock` and the repo mounted. Rationale: ships with the compose file, no host install step, works on any docker host. Host-side systemd service rejected (per-OS install, outside compose). Trade-off: socket access equals root on host, mitigated by token auth, internal-only network, fixed operations only.
2. **Repo mount at the identical absolute path.** `compose build` resolves the context and bind mounts as host paths via the daemon, so the sidecar mounts `${DARKSTAR_REPO_DIR}` to the same path inside (compose file sets `DARKSTAR_REPO_DIR=${PWD}` documented in `.env`) and runs `docker compose --project-directory <path> -p <project>`. Updater mounts `./data` read-only for the DB gate.
3. **Transport.** Updater is a small stdlib-based HTTP service (no new deps) on port 5001, no `ports:` publish, on the default compose network. Darkstar backend router `/api/updater/{status,check,channel,apply,log}` proxies with `Authorization: Bearer $DARKSTAR_UPDATER_TOKEN` (async aiohttp, 5 s timeout). Token from `.env` (`DARKSTAR_UPDATER_TOKEN`, generated once by a documented one-liner; updater refuses to start with an empty token). Darkstar env `DARKSTAR_UPDATER_URL=http://updater:5001` plus a non-empty token marks the feature opted in; without the token the router returns 404 and the UI hides everything.

   **Opt-in / backward compatibility.** The `updater` service sits behind compose profile `updater` (`COMPOSE_PROFILES=updater` in `.env`). `DARKSTAR_UPDATER_TOKEN` and `DARKSTAR_REPO_DIR` use `${VAR:-}` defaults (the repo mount uses a placeholder default) so `docker compose config/build/up` work with no `.env`; the updater entrypoint still refuses empty values. Manual `git pull && docker compose build && up -d` installs behave exactly as before.
4. **Channel state** lives in the updater (`updater-state` named volume, `state.json`: channel, last check result, last apply). Darkstar reads it via the API, so there is a single source of truth and nothing in `config.yaml`. Default derived from the current `VERSION` prefix (`dev-` means dev). The Settings channel selector calls `PUT /channel`.
5. **Targets.** dev: `origin/main`. stable: `git -c versionsort.suffix=- tag --list 'v*' --sort=-v:refname | head -1` (pre-releases sort below their final release). Dev version string = `VERSION` file at target (`git show <sha>:VERSION`) with short sha fallback; stable = tag minus `v`. Update available = target sha != HEAD sha (stable to dev allowed, dev to older stable allowed subject to the DB gate).
6. **Apply sequence** (single-flight lock, runs as a background thread, log to `updater-state/apply.log`): gates, record `prev=HEAD`, checkout target (dev: `git checkout main && git merge --ff-only origin/main`; stable: `git checkout --detach <tag>`), `docker compose build darkstar` with build args `DARKSTAR_VERSION`, `DARKSTAR_RELEASE_CHANNEL`, then `up -d --no-deps darkstar`. Build failure: `git checkout <prev>` (or `main`), status `failed`, container untouched. After `up -d`, poll Darkstar health for the target version (up to 5 min) to reach `done`, else `failed: unhealthy` (no auto rollback because DB migrations may have run; message points to the log and manual steps). `--no-deps` and the service name guarantee the updater never recreates itself; updater changes need a manual `docker compose up -d --build updater` (shown in the UI as a hint when the updater is older than the checkout: compare `updater/` tree hash baked as build arg).
6a. **Git runs as the repo owner** (`os.stat(repo)` uid/gid via subprocess `user=`/`group=`, `HOME`=repo) so root never writes root-owned objects into the host's `.git`/tree; root-owned repos are unchanged; docker compose stays root.
7. **Dirty tree** via `git status --porcelain --untracked-files=no`. The build args mean `VERSION` is never rewritten, so the tree stays clean (CI-committed `VERSION` is tracked).
8. **DB gate.** Read `SELECT version_num FROM alembic_version` via sqlite3 `mode=ro`. Revisions at target: `git ls-tree --name-only <ref> alembic/versions/` then `git show <ref>:<file>` and regex `^revision\s*(:\s*str)?\s*=\s*['"]([^'"]+)`. Pass if the DB revision is in that set, or the DB is absent/empty. Evaluated in `check` (so the UI disables Update early) and again in `apply`.
9. **Dockerfile.** Add `ARG DARKSTAR_VERSION=""` / `ARG DARKSTAR_RELEASE_CHANNEL=stable` -> `ENV`, wired from compose `build.args` with `${DARKSTAR_VERSION:-}`; GHCR builds keep the `stable` default so published images are unchanged. `get_version()` already prefers env, so no change in precedence; `/api/version` additionally exposes `commit` if available.
10. **Check cadence:** background thread every 6 h plus 30 s after updater start, manual check rate-limited to once per 10 s. Darkstar UI polls the cached `/status` on app load and every 30 min to drive the sidebar dot and banner.
11. **Reconnect.** After apply the UI polls `/api/health` (tolerating failures) until it answers with the target version, then reloads. Log is polled from `/api/updater/log?offset=N` incrementally.
12. **Tests.** Updater logic split into pure modules taking a `GitRunner`/`DockerRunner` protocol; tests use fakes and temp git repos created locally (no network), Darkstar router tests use a fake updater client; frontend tests mock the API.

## Risks / Trade-offs

- Docker socket in the sidecar is root-equivalent: mitigated as in decision 1; documented.
- Building on the host can be slow or fail on low-RAM hosts (Pi): failure leaves old container; UI shows log tail.
- Existing installs opt in with a one-time step (set token and repo dir in `.env`, enable the `updater` profile, `up -d --build`); others are unaffected.
- Unhealthy-after-up has no auto rollback because migrations may be applied; chosen to avoid DB/code mismatch.
- Compose `build.args` env interpolation requires the updater to pass env vars to the compose subprocess; covered by tests via fake runner assertions.
- Pre-release tags count as stable (but rank below their final release); if the maintainers later want only final releases, the tag filter is one function.

## Open Questions

- UI layout agreed: sidebar/mobile version dot, floating update card, dismissible banner per target version. Docs edit to docs/OPERATIONS.md approved.
- Whether `/api/version` should expose commit (recommended: yes, additive).
