## Context

Darkstar runs as stable/dev Home Assistant add-ons or standalone Docker deployments. FastAPI's lifespan already starts and stops independent services, configuration migration merges `config.default.yaml` while retaining user values, and onboarding/Settings already save through `/api/config/save`. `backend/core/version.py` supplies the app version and `backend/core/atomic_json.py` supports persistent JSON state.

The receiver will run separately in the maintainer's LXC, reached through Cloudflare Tunnel at `telemetry.wxl.se`. Both sender and receiver source must be available in this repository. The project is a small beta: use existing dependencies and simple UI, with no in-app upgrade notice.

## Goals / Non-Goals

**Goals:**
- Estimate active reporting installations and metadata distribution, including shadow-mode installations.
- Enable reporting by default, allow disabling and redirecting it, and retain explicit choices through upgrades.
- Keep reporting failures independent of planning, recording, and hardware control.
- Provide a small protected summary page and durable aggregate history on the receiver.

**Non-Goals:**
- Energy measurements, location, entity names, credentials, detailed configuration, crash reports, or feature-use events.
- Exact user/household counts, anonymous-data claims, or strong proof that public submissions are genuine.
- A dashboard framework, accounts database, additional notices, automatic Discord posting, or automatic deployment.
- Changes to Darkstar's learning database schema or files in `docs/`.

## Decisions

### Configuration and UI

Use a top-level `installation_stats` section with `enabled: true` and `endpoint: https://telemetry.wxl.se/api/ping`. The existing template merge supplies missing values on upgrade and must preserve explicit `false` and custom endpoints. Both backend and frontend must agree on defaults when old configuration is read before migration. Require a real boolean and an absolute HTTPS URL without embedded credentials, query, or fragment; malformed configuration skips reporting rather than blocking startup.

Add a normal, searchable Installation statistics section to Settings → System, exposing the toggle and endpoint. Add the same toggle and concise field disclosure to the existing final onboarding review step; save the choice with the existing finish patch before marking setup complete. Do not add a wizard step, reopen onboarding for existing users, or alter readiness/go-live/shadow-mode behavior. A rerun reflects the saved choice. Changes use existing design-system components and tokens.

Two controls give users the requested ownership without adding knobs for timing, retention, or individual fields. Opt-in was considered; the agreed default is opt-out for fresh installs and upgrades. Communication to existing users is via the eventual commit and the maintainer's Discord announcement.

### Identity and payload

Send exactly `installation_id`, `version`, `release_channel`, `installation_type`, `architecture`, and `inverter_profile`. Build this allowlisted object explicitly, never serialize configuration and remove selected keys afterward. The receiver assigns its own UTC last-seen timestamp.

- ID: random UUIDv4 persisted with the last attempt timestamp using atomic JSON writes under the existing persistent `data/` directory. If state cannot be read or saved safely, skip reporting instead of creating an ephemeral ID. Missing state represents a new installation; corrupted state must not generate a new ID every restart.
- Channel: `stable`, `dev`, or `unknown`, supplied explicitly by add-on/container build metadata. A beta version of the stable add-on is still `stable`; do not infer `dev` from the word beta. Docker defaults to `stable` with an explicit dev override; an unclassified source checkout uses `unknown`.
- Type: `ha_addon`, `docker`, or `unknown`, supplied by deployment metadata, without sending Supervisor tokens or host identifiers.
- Architecture: normalize known aliases to `amd64` or `aarch64`, otherwise `unknown`.
- Profile: maintain a deliberate allowlist of shipped identifiers. An unconfigured profile is `unknown`; a configured identifier outside the shipped allowlist is `custom`. Never infer the allowlist from arbitrary YAML files users can add.

The stable and dev add-on scripts currently link the same `/share/darkstar` data location. Use channel-scoped state files (`data/installation_stats.<channel>.json`) so simultaneously running stable/dev instances remain separate without changing the existing storage layout. Ordinary upgrades within a channel keep their ID. Copies of persistent data can share an ID; this is an acknowledged estimate, with no fingerprinting or household deduplication.

### Sender lifecycle and scheduling

Implement a small `backend/services/installation_stats_service.py` service managed by FastAPI lifespan. Use the existing async HTTP client dependency, a five-second total timeout, HTTPS verification, and no redirects. Reporting errors are caught within this service and logged briefly without payloads or sensitive URL details.

A first due attempt occurs after a random 1–15 minute startup delay. Subsequent attempts are due at least 24 hours after the persisted previous attempt, with 0–15 minutes jitter. Record an attempt before sending so errors or restarts cannot cause a tight retry loop. Persisting attempts also avoids daily pings on every restart. There is no immediate retry and no backlog upload after an outage.

Recheck configuration while waiting (at most 30 seconds between checks) and immediately before dispatch. A successful UI save wakes the service to re-evaluate its enabled state; disabling prevents all subsequent requests, and an already-dispatched request may finish. Re-enabling follows the due schedule. Manual YAML edits are observed by the next check. Shutdown cancels waiting/in-flight work and closes the client without waiting for the daily interval. State, client, config, and network errors never fail the application lifespan or affect energy-control services.

### Receiver and storage

Create an independent `telemetry_receiver/` Python package, its own minimal pinned runtime requirements drawn from existing project pins, a systemd example, and a deployment README. Keep it out of normal Darkstar image copy/start paths. Use one Uvicorn worker and standard-library `sqlite3`, with bounded database operations off the event loop, transactions, busy timeout, and WAL mode. The standalone database contains an installations table (ID primary key, latest payload metadata, last-seen UTC) and daily aggregate snapshots. Do not import/start Darkstar's executor or connect to its databases.

`POST /api/ping` is public and accepts only the six bounded fields above. Require JSON, enforce a 2 KiB body limit even without Content-Length, reject extra fields, validate UUIDv4/enums/version length, and reject unknown profile values. Use parameterized SQL to upsert a single row per ID. Return an empty 204 response only after a successful commit. Never retain request bodies, IP addresses, forwarded headers, User-Agent values, or credentials in application logs/storage. Disable Uvicorn access logging. Cloudflare still processes request metadata under its own settings; deployment guidance must not promise otherwise.

Use a small global in-memory request limiter (60 ping requests/second, burst 60) to bound ingestion during spikes, returning 429 with Retry-After before database work. It uses no IP identifiers and is appropriate to the single-worker deployment. Keep request limits simple; an embedded shared sender secret would be extractable and would not establish genuine installations.

### Counts, history, and cleanup

For an as-of UTC time, count distinct IDs whose `last_seen` is within the previous 7 or 30 days, including the boundary. Break down each window by version, channel, installation type, architecture, and profile using the latest metadata in each ID's row. Label results as active reporting installations, including shadow mode, rather than total users or healthy executors.

At startup and once per UTC day, store an aggregate snapshot of the two totals and those breakdowns with a sample timestamp; enforce one snapshot per UTC date. Aggregate rows contain no IDs. Mark today as a sampled/partial day and retain snapshots indefinitely. Receiver downtime leaves history gaps rather than inventing historical counts. Remove installation rows strictly older than 60 days at startup and daily; snapshots survive cleanup. Stored pings remain deduplicated after receiver restarts.

### Protected summary and deployment

Serve simple HTML at `/` and aggregate JSON at `/api/stats`, protected by HTTP Basic authentication over the public HTTPS connection. Configure username/password only through server environment variables; refuse receiver startup if credentials are absent. Use UTF-8 byte comparisons with `secrets.compare_digest`, generic 401 responses, and `WWW-Authenticate`. Protect every statistics/history route, disable public API docs/schema, and return `Cache-Control: no-store` on summary/statistics responses. Escape metadata in HTML. Use local styling that follows Darkstar tokens without importing its full frontend or external CDN assets.

The page displays current 7/30-day totals, small metadata breakdown tables, and aggregate history. There are no installation lists, raw payload downloads, login screens, or user management. HTTP Basic provides browser-native authentication without a new dependency or Cloudflare-specific token verification. See [FastAPI HTTP Basic documentation](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/).

Route the public hostname through a persistent Cloudflare Tunnel to the receiver's local listener. In the simplest same-LXC setup, bind to loopback and run `cloudflared` there; if the connector is elsewhere, limit the private listener to that connector. No Cloudflare login/challenge may block `/api/ping`. Keep Basic authentication on the read routes at the application layer. Cloudflare Tunnel uses outbound connections and avoids exposing an origin port publicly; see [Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).

## Risks / Trade-offs

- Opt-outs, blocked networks, copies/reinstalls, and fake UUIDs make counts approximate → Label them accurately and avoid treating them as billing or user counts.
- Stable/dev share existing config and data paths → Channel-scope identity; do not restructure storage as part of this feature. A shared config naturally shares the enabled/endpoint choice.
- Receiver downtime causes missed observations → Daily attempts resume without affecting Darkstar; active windows tolerate brief outages and history keeps gaps.
- UUIDs link daily reports → Describe the data as pseudonymous, collect only the agreed fields, and expire individual records after 60 days.
- A public endpoint can receive garbage → Bounded validation, global throttling, parameterized queries, and edge controls if later needed; no elaborate anti-fraud system.
- Default reporting changes outbound behavior on upgrade → Preserve explicit opt-outs and describe disabling in the eventual commit/Discord text, without adding an in-app upgrade notice.

## Migration Plan

1. Implement and test artifacts in this change without changing local production config, existing database schemas, or deployment infrastructure.
2. Deploy the standalone receiver to the LXC, set private credentials/storage, and route `telemetry.wxl.se` through Cloudflare Tunnel. Verify protected reads and a public valid ping before distributing a sender release.
3. Ship the enabled default and both UI controls. The existing config merge supplies absent fields and keeps explicit choices. Include opt-out instructions in the eventual commit description; the maintainer posts the Discord announcement.
4. Roll back reporting by setting `installation_stats.enabled: false` or reverting the sender release. The receiver can stop independently; no Darkstar data migration is required.

## Open Questions

None block implementation. LXC connection details, credentials, and Cloudflare Tunnel provisioning are operator-supplied deployment values, not repository secrets or prerequisites for writing/testing the implementation.
