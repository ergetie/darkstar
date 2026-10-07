# Telemetry Receiver

## Purpose

Defines the independent receiver for validated telemetry ingestion, aggregate history, and protected statistics.

## Requirements

### Requirement: Independent transparent receiver deployment
The repository SHALL contain a separately runnable receiver and deployment README under `telemetry_receiver/`. It SHALL reuse currently pinned runtime dependencies and standard-library SQLite, operate without Darkstar's configuration/executor/learning databases, and remain outside normal Darkstar container start paths. Deployment examples SHALL cover a single-worker service in an LXC, persistent database storage, environment-supplied credentials, and a persistent Cloudflare Tunnel serving `telemetry.wxl.se` over HTTPS.

#### Scenario: Run the receiver independently
- **WHEN** the receiver starts with its own database path and credentials
- **THEN** it starts without a Home Assistant connection or Darkstar `config.yaml`
- **AND** starting a normal Darkstar install does not start the receiver

### Requirement: Bounded public ping ingestion
`POST /api/ping` SHALL accept either the legacy six-field heartbeat or the current seven-field heartbeat without requiring authentication. The current payload SHALL add only `execution_mode`, restricted to `shadow`, `live`, or `unknown`; legacy payloads SHALL be normalized to `execution_mode: unknown`. Both shapes SHALL reject every other extra or missing field. The receiver SHALL validate UUIDv4, allowed enums and inverter identifiers, and a non-empty version of at most 128 characters. It SHALL reject bodies larger than 2 KiB, including streamed bodies without Content-Length. It SHALL apply a global in-memory limit of 60 ping requests/second with burst 60 before database writes, returning 429 and Retry-After when exceeded. Invalid submissions SHALL NOT create or modify installation records.

#### Scenario: Current and legacy public pings
- **WHEN** a valid seven-field or legacy six-field payload is posted without credentials
- **THEN** the receiver commits the row update and returns an empty HTTP 204 response
- **AND** a legacy payload is stored with execution mode `unknown`

#### Scenario: Invalid or oversized payload
- **WHEN** a payload has extra fields, invalid IDs/enums or execution mode, an unrecognized profile identifier, or an oversized version
- **THEN** it receives a 4xx validation response and no database mutation
- **AND** a body over 2 KiB receives HTTP 413 even without Content-Length

#### Scenario: Request burst
- **WHEN** ping traffic exceeds the global request budget
- **THEN** the receiver returns HTTP 429 with Retry-After before writing to SQLite
- **AND** the limiter does not retain IP identifiers

### Requirement: Durable deduplicated latest observations
The receiver SHALL store at most one installation row per ID, containing latest permitted metadata including execution mode and its own UTC last-seen timestamp. It SHALL use parameterized SQL, bounded off-event-loop database work, transactions, WAL mode, and a busy timeout. A storage failure SHALL NOT return success or alter unrelated records. Repeated pings SHALL update the row without increasing distinct installation counts; receiver restarts SHALL retain observations.

#### Scenario: Repeat ping with a new version
- **WHEN** an existing ID sends another valid heartbeat with a different version
- **THEN** its metadata and receiver-assigned last-seen time are updated
- **AND** it remains one installation

#### Scenario: Executor mode changes
- **WHEN** one ID reports `shadow` and later reports `live`
- **THEN** the latest observation and active-window breakdowns use `live`
- **AND** the ID still contributes one installation

#### Scenario: Client timestamp is rejected
- **WHEN** a client adds a timestamp to the otherwise valid payload
- **THEN** validation rejects the extra field
- **AND** only receiver time can determine last-seen values

#### Scenario: Receiver restart or failed write
- **WHEN** the receiver restarts
- **THEN** it retains committed rows and counts
- **AND** a subsequent failed database write returns an error rather than HTTP 204

### Requirement: Active windows and metadata breakdowns
The receiver SHALL report distinct installation counts for 7-day and 30-day trailing windows relative to an explicit as-of UTC time, including the lower boundary. Each window SHALL include breakdowns by latest version, release channel, installation type, architecture, inverter profile, and execution mode. Each breakdown's counts SHALL sum to its window total. Summary labels SHALL describe active reporting installations and SHALL NOT claim exact users, households, or healthy executors. Empty datasets SHALL return zero counts and empty breakdowns.

#### Scenario: Execution mode counts for both windows
- **WHEN** active installations have reported `shadow`, `live`, and `unknown` modes
- **THEN** both the 7-day and 30-day breakdowns include those latest mode counts
- **AND** mode changes are counted once according to the latest observation

#### Scenario: Window boundaries
- **WHEN** IDs last reported exactly 7 days ago, 10 days ago, exactly 30 days ago, and more than 30 days ago
- **THEN** the 7-day total is one and the 30-day total is three
- **AND** every category breakdown sums to its window's total

#### Scenario: Latest metadata and no observations
- **WHEN** an ID changes metadata within an active window
- **THEN** its contribution appears only under its latest categories
- **AND** an empty database reports zero totals and empty breakdowns

### Requirement: Aggregate history and individual retention
At startup and once per UTC day the receiver SHALL record one aggregate snapshot per UTC date, including its actual sample timestamp, both active-window totals, metadata breakdowns, and execution-mode breakdowns. Snapshot records SHALL contain no installation IDs and SHALL survive individual-record cleanup indefinitely. The current day's sample SHALL be labeled as partial/sampled; missed days SHALL remain gaps. At startup and daily, the receiver SHALL delete installation records strictly older than 60 days since last report. Startup SHALL apply an additive, idempotent SQLite migration: existing installation rows SHALL receive mode `unknown`, and existing snapshots SHALL retain their stored times, totals, and metadata breakdowns while their new mode counts represent their recorded totals as `unknown`. The migration SHALL NOT infer historic modes from current observations.

#### Scenario: Stale records expire
- **WHEN** cleanup runs with records aged exactly 60 days and more than 60 days
- **THEN** the exactly-60-day record remains and the older record is deleted
- **AND** previously stored aggregate snapshots remain unchanged

#### Scenario: Upgrade from the original SQLite schema
- **WHEN** the receiver starts with the original six-field observation and snapshot schema
- **THEN** it preserves every observation, timestamp, total, and existing breakdown
- **AND** it adds unknown mode values for old rows and historical snapshots
- **AND** subsequent startups do not alter the migrated historical mode counts

#### Scenario: Repeated startup and outage
- **WHEN** the receiver restarts multiple times in a UTC day
- **THEN** it retains at most one aggregate snapshot for that date
- **AND** days missed during receiver downtime are not backfilled with invented values

### Requirement: Protected simple summary on the public hostname
The receiver SHALL serve a simple HTML summary at `/` and aggregate JSON/history through `/api/stats` on `telemetry.wxl.se`, protected by HTTP Basic authentication over HTTPS. Credentials SHALL come from server environment variables and missing/empty credentials SHALL refuse startup. All read routes SHALL enforce authentication with constant-time credential comparison, return generic HTTP 401 with WWW-Authenticate for invalid credentials, and disable caching. Public API docs/schema SHALL be disabled. The page SHALL show current totals, metadata and execution-mode breakdowns for both windows, and aggregate history using local styling and safely escaped values, without exposing individual IDs or payloads. Its explanatory text SHALL describe mode as the latest reported setting and explain that unavailable and pre-migration modes are `unknown`.

#### Scenario: Unauthorized statistics access
- **WHEN** a visitor requests `/` or `/api/stats` without valid credentials
- **THEN** it receives HTTP 401 with WWW-Authenticate and no statistics
- **AND** the public `/api/ping` route still accepts valid unauthenticated submissions

#### Scenario: Authenticated summary
- **WHEN** the operator requests the page with valid credentials
- **THEN** the totals, six breakdown categories including execution mode, and aggregate history are visible
- **AND** responses use Cache-Control no-store, safely render supplied metadata, and contain no installation IDs

#### Scenario: Credentials absent
- **WHEN** receiver username or password is missing or empty
- **THEN** receiver startup fails instead of exposing unprotected read routes

### Requirement: Minimal storage and logging
Receiver storage and application logs SHALL NOT retain raw request bodies, source IP addresses, forwarded headers, User-Agent values, or authentication credentials. Uvicorn access logging SHALL be disabled in the deployment example. Deployment guidance SHALL distinguish application retention from Cloudflare's processing, describe the public ping/protected reads split, and keep server secrets and runtime database files out of version control.

#### Scenario: Accepted, rejected, and authenticated requests
- **WHEN** valid or invalid pings and authenticated summary requests are handled
- **THEN** application logs/storage contain none of the prohibited request information or credentials
- **AND** runtime files and server secrets are excluded from committed artifacts
