# Proposal

## Why

Plain-Docker installs update only by SSH'ing in and running `git pull && docker compose build && docker compose up -d` (docs/OPERATIONS.md "Updating Darkstar"). Users want to check for and apply updates from the UI, without handing the Darkstar container the Docker socket.

## What Changes

- New small **updater sidecar** service in `docker-compose.yml` that owns the Docker socket and the repo mount, and performs `git fetch` / checkout / `docker compose build` / `up -d` for the `darkstar` service only.
- Darkstar backend gains `/api/updater/*` endpoints that proxy to the sidecar over the internal compose network with a shared-secret bearer token. The feature is hidden when `DARKSTAR_INSTALLATION_TYPE` is not `docker` or the updater is unreachable/unconfigured.
- Update **channels** switchable in Settings: `dev` (tip of `main`) and `stable` (latest `v*` tag). Updates build locally from git; GHCR images and CI are untouched.
- Periodic background check (every 6 h) plus manual "Check now"; UI shows "update available" with target version and commit summary.
- Apply streams progress/log to the UI, UI shows restarting and reconnects, failures are reported clearly. A failed build leaves the old container running.
- Safety gates: refuse on dirty tracked files; block targets whose `alembic/versions` lack the DB's current revision ("Stable doesn't include your database version yet"). No automatic downgrades, no pre-update backup.
- Dockerfile takes `DARKSTAR_VERSION` / `DARKSTAR_RELEASE_CHANNEL` build args (the current hard-coded `stable` ENV is wrong for locally built dev installs).
- Settings > System gets an "Updates" card. **Exact UI layout is to be agreed with the user before building.**

## Capabilities

### New Capabilities
- `docker-self-update`: update check, channel selection, safety gates, apply with progress, and updater isolation for plain-Docker installs.

### Modified Capabilities

## Impact

- `docker-compose.yml` (new `updater` service, shared token, internal network), new `updater/` directory (Dockerfile + service), `Dockerfile` (build args), `backend/core/version.py` unchanged in precedence (env first), new `backend/api/routers/updater.py` + client service, frontend Settings System tab + API client, `.env`/token bootstrap, docs (to be updated later with user approval; docs/ is not touched by this change's planning).
- Compose gets a new mandatory secret (`DARKSTAR_UPDATER_TOKEN`); existing installs must add the updater service once via a manual `git pull && docker compose up -d --build` (one-time migration).
- No new Python dependencies for Darkstar; updater uses stdlib `http.server`-class minimal service or FastAPI already in requirements (decide in design). No DB schema changes.
