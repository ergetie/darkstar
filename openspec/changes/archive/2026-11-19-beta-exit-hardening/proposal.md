# Proposal

## Why

The beta-exit audit (2026-11) found a set of small, independent hardening gaps: any website open in a LAN browser can drive the write API, unitless power sensors are silently read as kW, a missing or empty schedule never raises an alert, a Discord webhook secret can reach logs and the diagnostics bundle, logs and Docker output have no size cap, the add-on overwrites `secrets.yaml` on every start, and CI lacks `tsc`, `vite build` and vitest in the pre-push gate. Two user requirements are added: the UI must not hardcode a currency (the 7-day price outlook tooltip shows SEK/kWh values labelled "öre") and must show times in the browser's timezone instead of a hardcoded Europe/Stockholm.

## What Changes

- Replace `CORSMiddleware(allow_origins=["*"])` with an outermost ASGI guard that rejects non-safe requests (and WebSocket handshakes) whose `Sec-Fetch-Site` is `cross-site` or `same-site`; Socket.IO CORS is disabled; three self-parsing handlers get typed bodies.
- Add config key `sensor_unit_overrides` (entity id to `W` or `kW`), one unit resolver used by every power-reading site (unitless sensors keep being read as kW, logged once), a backend-computed `unit_needed` list in the readiness response and a draft-config sensor-units endpoint, and a W/kW selector inside the shared entity picker in onboarding and Settings that appears automatically for entities in that list.
- Executor: every no-valid-schedule cause (missing, unreadable, empty, no `generated_at`, stale) raises one deduplicated error notification; stale-warning state resets on every path; wording becomes "no valid schedule, idle fallback".
- Scrub URLs and token patterns in `describe_exception`; Discord webhook failures log only exception class and status.
- Logging: size-based `RotatingFileHandler` (10 MiB x 5 backups), clear-logs removes backups, diagnostics includes `darkstar.log.1`; docker-compose json-file limits.
- Add-on `run.sh`: stop overwriting `secrets.yaml`, move merge logic into a tested `backend/addon_bootstrap.py`, remove dead options, make the timezone option optional.
- CI: `typecheck` script, `tsc --noEmit` and `pnpm build` in CI, and typecheck, vitest and build in `scripts/ci_local.sh`.
- Currency: one config-sourced currency exposed to the frontend, one formatting helper (unit and subunit derived from the ISO code), all hardcoded labels replaced, tooltip fixed; backend messages use a backend helper. `_sek` keys are NOT renamed.
- Timezone: display uses the browser timezone and locale-independent keys; backend-defined buckets and tariff windows keep `config.timezone`; three UTC-date bugs fixed.
- `docs/BACKLOG.md`: covered entries removed or trimmed; optional authentication and per-profile idle fallback kept as their own entries.

## Capabilities

### New Capabilities
- `cross-site-write-protection`: API and Socket.IO reject browser cross-site and same-site writes and handshakes.
- `sensor-unit-overrides`: power units resolved from HA or a user override; unitless sensors keep being read as kW but are flagged, and the backend tells the UI which selected entities need a unit.
- `schedule-fallback-alerting`: missing, empty, unreadable, stale or timestamp-less schedule is alerted once per transition.
- `log-secret-scrubbing`: URLs and tokens never appear in logged exception text.
- `log-size-cap`: bounded log files and container logs.
- `addon-secrets-preservation`: add-on start preserves user secrets and only applies explicit options.
- `configured-currency-display`: all currency labels derive from `nordpool.currency`.
- `browser-display-timezone`: UI display uses the browser timezone.
- `frontend-typecheck-build-gate`: typecheck, vitest and build gate CI and pre-push.

### Modified Capabilities
<!-- None: all behavior is captured as new capabilities. -->

## Impact

- Backend: `backend/main.py`, `backend/middleware/fetch_site.py` (new), `backend/core/websockets.py`, `backend/api/routers/{executor,forecast,system,config,debug,analyst}.py`, `backend/core/{ha_client,water_progress,readiness,exception_text,logging,currency}.py`, `backend/loads/service.py`, `backend/ha_socket.py`, `backend/notify.py`, `backend/strategy/engine.py`, `backend/addon_bootstrap.py` (new), `executor/engine.py`.
- Config: new `sensor_unit_overrides` in `config.default.yaml` (user approved).
- Frontend: new `lib/currency.ts`, `lib/timezone.ts`, `SensorUnitSelect`; edits across charts, settings, onboarding.
- Ops: `darkstar/run.sh`, `darkstar-dev/run.sh`, both add-on `config.yaml`, `docker-compose.yml`, `.github/workflows/ci.yml`, `scripts/ci_local.sh`, `frontend/package.json`.
- Add-on schema: `timezone: str?`.
