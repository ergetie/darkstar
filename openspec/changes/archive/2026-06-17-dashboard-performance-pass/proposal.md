## Why

A single dashboard refresh takes ~5 seconds and pins one CPU core, while RAM and other cores sit idle. Profiling on the production server traced this to three independent "rebuild-from-scratch-every-request" patterns on the web path — none of which are compute the system actually needs:

1. **Config re-parsing** — every API request re-opens and re-parses the 22 KB `config.yaml` (and `secrets.yaml`); measured at **68 ms per parse**, dozens of times per refresh.
2. **Unbounded forecast query** — `/api/price-forecast/outlook` (and `/api/analyst/advice`) reads **all 48,391 rows** of `price_forecasts` and formats dates ~97,000 times to produce a 7-day summary.
3. **Per-call HTTPS client** — every Home Assistant read builds a new `httpx.AsyncClient`, reloading the TLS/CA trust store each time (`load_verify_locations` was the single largest cost in `/api/status` and `/api/health`).

Because the work is CPU-bound on one thread (the GIL), the ~20 concurrent requests a dashboard refresh fires cannot overlap — they serialize into 6–11 s. This also starves the executor tick, blocking the goal of sub-second control loops.

## What Changes

- **Cache parsed config with mtime detection on the shared web-path loader.** Extend the existing config-caching behavior (today only in the executor) to `backend/core/secrets.py:load_yaml`, so all ~71 read sites and per-entity `secrets.yaml` reads reuse a cached parse. Re-parse only when the file's mtime changes (covers runtime config writes from migrations/reflex). Callers receive a copy to prevent cache corruption.
- **Route direct config parses through the cached loader.** Convert sites that call `yaml.safe_load(open("config.yaml"))` directly (e.g. `backend/health.py`, `backend/core/ha_client.py:get_initial_state`, `backend/core/price_outlook.py`) to use the cached loader.
- **Bound the price-outlook query to the latest forecast run.** Filter `get_daily_outlook` by the most recent `issue_timestamp` so it reads ~168 rows instead of 48,391, eliminating the per-row date-formatting storm. Endpoint output and classifications are unchanged.
- **Reuse a single shared Home Assistant HTTP client.** Replace per-call `httpx.AsyncClient(...)` construction across the core HA paths with one shared, connection-pooled client (created lazily, closed on app shutdown), honoring the connection-pooling requirement the async-http-client capability already specifies.
- **Enable live profiling in the container.** Add `cap_add: [SYS_PTRACE]` to `docker-compose.yml` so `py-spy` can attach to the running process, and document the profiling workflow in developer/operations docs.
- **Verify the result.** Re-run the server CPU/wall benchmark after the changes to confirm a refresh drops from ~5 s to well under 1 s.

## Capabilities

### New Capabilities
<!-- None — this change extends behavior of existing capabilities. -->

### Modified Capabilities
- `config-caching`: Extend mtime-based config caching beyond the executor tick to the shared `load_yaml` loader used by the web/API request path, including `secrets.yaml`, with copy-on-read semantics.
- `async-http-client`: Require the Home Assistant HTTP client to be reused across calls (shared instance, pooled connections, reused TLS context) rather than reconstructed per request, in the core (`backend/core/ha_client.py`) request path.
- `price-outlook-api`: Require the daily outlook query to be bounded to the latest forecast run for efficiency, while preserving all existing response fields, classifications, and statuses.

## Impact

- **Code**: `backend/core/secrets.py` (cached loader), `backend/core/ha_client.py` (shared client + cached config), `backend/health.py`, `backend/api/routers/ha.py`, `backend/learning/backfill.py` (HTTP client reuse + cached config), `backend/core/price_outlook.py` (bounded query).
- **Infra**: `docker-compose.yml` gains `cap_add: [SYS_PTRACE]`.
- **Docs**: `docs/DEVELOPER.md` (py-spy profiling), `docs/OPERATIONS.md` (debugging note).
- **Behavior**: No API contract or output changes; purely latency/CPU reduction. Config writes remain effective via mtime invalidation.
- **Risk**: Low. Main care points — cache must invalidate on runtime config writes (mtime handles this), and the shared HTTP client must be bound to the running event loop and closed on shutdown.
