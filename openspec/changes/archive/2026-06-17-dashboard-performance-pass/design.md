## Context

Profiling on the production server (`darkstar`, v2.6.2-beta) established the dashboard's ~5 s refresh is CPU-bound on a single core, not I/O- or resource-bound:

- A full 11-endpoint refresh burned **4.37 s CPU / 4.74 s wall (92% CPU-bound)**.
- `config.yaml` (22 KB) parse via `yaml.safe_load`: **68 ms each**, no caching; ~17+ config parses per refresh plus per-entity `secrets.yaml` parses.
- `get_daily_outlook` read **48,391 rows** from `price_forecasts` and called `date.strftime` **~97,000 times per request** to emit a 7-day summary (py-spy/cProfile: 6.9 s of strftime over 10 runs).
- Every Home Assistant read constructs a fresh `httpx.AsyncClient`; `load_verify_locations` (TLS/CA load) was the top cost in `/api/status` (5×/req) and `/api/health` (21×/req).

The GIL serializes this CPU work, so the ~20 concurrent requests a refresh fires queue into 6–11 s. Two relevant specs already exist but are scoped to the executor only: `config-caching` (mtime cache per tick) and `async-http-client` (already requires connection pooling). The web/API path honors neither.

## Goals / Non-Goals

**Goals:**
- Eliminate redundant per-request work on the web path: cache config, bound the outlook query, reuse one HTTP client.
- Reduce a dashboard refresh from ~5 s to well under 1 s with no change to any API response.
- Make live profiling (`py-spy`) usable on the deployed container for future debugging.

**Non-Goals:**
- No multi-worker / multi-process web server (the executor, scheduler, and recorder run in-process as singletons; multiple workers would duplicate them).
- No change to API response shapes, classifications, or statuses.
- No rewrite of the executor's existing config-caching (already in place); this extends the same idea to the web path.
- Not addressing the secondary `get_trailing_avg` aggregate scan (already `LIMIT 14`, minor) beyond noting it.

## Decisions

### Decision 1: Cache config in the shared `load_yaml` loader, keyed by path, with mtime detection and copy-on-read
`backend/core/secrets.py:load_yaml(path)` becomes the single cached entry point. On each call it `stat()`s the file; if the mtime matches the cached entry it returns a **deep copy** of the cached parse, otherwise it re-parses, stores `(mtime, parsed)`, and returns a copy. A module-level `threading.Lock` guards the cache because it is read from the event loop, `asyncio.to_thread` workers, and the executor thread.

- **Why mtime, not parse-once-forever:** config is rewritten at runtime (startup migration, `reflex` updates). mtime invalidation transparently picks up both external edits and the app's own writes. Matches the existing executor `config-caching` approach for consistency.
- **Why copy-on-read:** callers occasionally mutate the dict they receive; sharing the cached object risks silent cache corruption. A deep copy is ~microseconds vs. the 68 ms parse it replaces (still ~1000× cheaper). (User-selected.)
- **Why `stat()` per call is fine:** a stat is a sub-millisecond syscall, negligible against a 68 ms parse, and keeps semantics simple.
- **Alternatives considered:** `functools.lru_cache` (no invalidation — stale after writes); caching only in `get_config()` (misses the ~70 direct `load_yaml` sites); a TTL cache (either too stale or re-parses needlessly).

### Decision 2: Route direct config parses through the cached loader
Sites that bypass `load_yaml` with `yaml.safe_load(open("config.yaml"))` — `backend/health.py` (config + secrets), `backend/core/ha_client.py:get_initial_state`, `backend/core/price_outlook.py:get_daily_outlook` — are converted to call the cached loader, or they would keep paying the parse cost. This is an audit-and-replace task, not a behavior change.

### Decision 3: Bound `get_daily_outlook` to the latest forecast run via `issue_timestamp`
The query becomes `WHERE days_ahead BETWEEN 1 AND 7 AND issue_timestamp = (SELECT MAX(issue_timestamp) FROM price_forecasts)`, reading ~168 rows instead of 48,391 and removing the per-row date formatting.

- **Why latest-run-only is safe:** verified on the server that each `days_ahead` value has identical row counts (6,913 each) — every forecast run writes a complete D+1..D+7 set, so the newest run is complete. A guard returns an empty list (existing `no_data` path) if the latest run is unexpectedly empty.
- **Alternative considered:** "latest `issue_timestamp` per slot_start" (a per-slot MAX, more robust to partial runs) — rejected as unnecessary complexity given runs are complete, but noted as the fallback if partial runs ever appear.
- Output is identical: the existing per-day aggregation, dedup, classification, and 7-day cap all still run on the (now small) result set.

### Decision 4: One shared, pooled Home Assistant `httpx.AsyncClient`
Replace per-call `httpx.AsyncClient(...)` construction in the core HA path (`backend/core/ha_client.py`, and the other sites in `backend/health.py`, `backend/api/routers/ha.py`, `backend/learning/backfill.py`) with a single lazily-created client retrieved via a helper (e.g. `get_ha_http_client()`). The client is created on first use, reused for all subsequent reads (pooling connections and reusing the TLS context), and closed on FastAPI lifespan shutdown.

- **Why a shared client:** `httpx` is explicitly designed for reuse; constructing per call re-runs TLS/CA loading and discards the connection pool. This directly satisfies the existing `async-http-client` "Connection pooling" requirement that the core path currently violates.
- **Event-loop binding:** the app runs a single event loop; the singleton is bound to it and closed on shutdown. Per-request timeouts remain configurable per call.
- **Alternative considered:** a shared `httpx.HTTPTransport`/`SSLContext` only — rejected; a shared client is simpler and also gives connection reuse.

### Decision 5: Enable `py-spy` via `SYS_PTRACE`
Add `cap_add: [SYS_PTRACE]` to the `darkstar` service in `docker-compose.yml` so `py-spy` can attach to PID 1's Python process for live flame/sampling profiles. Document the workflow (install/attach/record) in `docs/DEVELOPER.md` and a debugging pointer in `docs/OPERATIONS.md`.

## Risks / Trade-offs

- **[Stale config after a write] →** mtime-based invalidation re-parses whenever the file changes; the executor already uses this pattern reliably.
- **[Cache mutated by a caller] →** copy-on-read returns an independent object, so callers cannot corrupt the shared cache.
- **[Shared HTTP client outlives its event loop / not closed] →** create lazily against the running loop and close in the lifespan shutdown handler; failures fall back to existing per-call error handling.
- **[Latest-run filter hides data if a run is partial] →** verified runs are complete; empty-result guard returns the existing `no_data` response, and the per-slot-MAX approach is documented as a fallback.
- **[`SYS_PTRACE` capability] →** scoped to the single self-hosted container; grants in-container process tracing only, acceptable for a self-hosted deployment and gated behind the operator's own compose file.

## Migration Plan

1. Land code changes (config cache, direct-parse routing, outlook query, shared client) — all backward-compatible, no schema or API changes.
2. Add `cap_add: [SYS_PTRACE]` and docs.
3. Deploy; re-run the server CPU/wall benchmark to confirm refresh < 1 s and one core no longer pinned.
4. **Rollback:** revert the commit; no data migration is involved, so rollback is immediate.

## Open Questions

- None blocking. If partial forecast runs are ever introduced, switch Decision 3 to the per-slot `MAX(issue_timestamp)` variant.
