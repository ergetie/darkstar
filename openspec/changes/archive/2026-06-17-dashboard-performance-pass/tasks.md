## 1. Config caching on the shared loader

- [x] 1.1 Add an mtime-keyed, thread-safe cache inside `backend/core/secrets.py:load_yaml` (module-level dict `{path: (mtime, parsed)}` guarded by a `threading.Lock`); on each call `stat()` the file, re-parse only when mtime changed
- [x] 1.2 Return a deep copy of the cached parse to each caller (copy-on-read) so callers cannot mutate the shared cache
- [x] 1.3 Ensure `secrets.yaml` reads (via `load_home_assistant_config` / `load_notifications_config`) flow through the cached loader
- [x] 1.4 Audit and reroute direct `yaml.safe_load(open("config.yaml"/"secrets.yaml"))` sites through the cached loader: `backend/health.py` (config + secrets), `backend/core/ha_client.py:get_initial_state`, `backend/core/price_outlook.py:get_daily_outlook`
- [x] 1.5 Add unit tests: cache hit on unchanged file (no re-parse), re-parse after mtime change, returned copy is independent of cache, concurrent reads stay consistent

## 2. Bound the price-outlook query

- [x] 2.1 In `backend/core/price_outlook.py:get_daily_outlook`, filter the query to `days_ahead BETWEEN 1 AND 7 AND issue_timestamp = (SELECT MAX(issue_timestamp) FROM price_forecasts)`
- [x] 2.2 Keep the existing per-day aggregation, dedup, classification, and 7-day cap operating on the reduced result set; guard the empty/missing-run case to return the existing `no_data` response
- [x] 2.3 Add a test asserting identical output for a complete latest run vs. the previous full-history processing, and that only latest-run rows are read

## 3. Shared Home Assistant HTTP client

- [x] 3.1 Add a shared, lazily-created `httpx.AsyncClient` accessor (e.g. `get_ha_http_client()`) in `backend/core/ha_client.py`, reused across calls (pooled connections, single TLS/CA load)
- [x] 3.2 Replace per-call `httpx.AsyncClient(...)` construction with the shared client in `backend/core/ha_client.py` (`get_ha_entity_state`, `get_energy_from_power_history`, `get_load_profile_from_ha`)
- [x] 3.3 Replace remaining per-call client construction sites in `backend/health.py`, `backend/api/routers/ha.py`, and `backend/learning/backfill.py` with the shared client
- [x] 3.4 Close the shared client on FastAPI lifespan shutdown
- [x] 3.5 Add a test asserting repeated HA reads reuse one client instance and preserve timeout/error behavior

## 4. Profiling enablement (py-spy)

- [x] 4.1 Add `cap_add: [SYS_PTRACE]` to the `darkstar` service in `docker-compose.yml`
- [x] 4.2 Document the py-spy live-profiling workflow (install, `py-spy dump`/`record` against the container process) in `docs/DEVELOPER.md`
- [x] 4.3 Add a short debugging pointer to py-spy profiling in `docs/OPERATIONS.md`

## 5. Verification

- [ ] 5.1 Deploy to the server and re-run the CPU/wall benchmark (full 11-endpoint refresh) to confirm CPU time drops sharply and wall time is < 1 s (NOT DONE — pending real deployment + benchmark)
- [ ] 5.2 Confirm `/api/status` and `/api/health` no longer show `load_verify_locations` as a hotspot (py-spy/cProfile spot check) (NOT DONE — pending real deployment + benchmark)
- [ ] 5.3 Confirm a config change at runtime is picked up (edit `config.yaml`, verify new value served without restart) (NOT DONE — pending real deployment + benchmark)
- [x] 5.4 Run the existing test suite / quality gate to confirm no regressions
