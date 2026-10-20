# Design

## Context

See proposal.md - Why. Current state:
- `backend/core/forecasts.py` `_fetch_forecast()` loops over arrays, opening `OpenMeteoSolarForecast(...)` and awaiting `estimate()` per array; any exception aborts the loop and the outer `except Exception` runs the stored-estimate fallback (`_get_stored_openmeteo_pv_for_slots`) or raises `PVForecastError`.
- The `open_meteo_solar_forecast` library maps responses as: 502/503 -> `OpenMeteoSolarForecastConnectionError`; 429 -> `OpenMeteoSolarForecastRatelimitError` (subclass of `OpenMeteoSolarForecastRequestError`); 400 -> `OpenMeteoSolarForecastRequestError`; 401/403 -> `OpenMeteoSolarForecastAuthenticationError`; 422 -> `OpenMeteoSolarForecastConfigError`; other non-2xx (500, 504) -> `aiohttp.ClientResponseError` via `raise_for_status()`; network errors surface as `aiohttp.ClientError` / `asyncio.TimeoutError`. Non-JSON -> base `OpenMeteoSolarForecastError`.
- `ml/weather.py` uses sync `requests.get(..., timeout=5)`; errors are caught and an empty DataFrame returned.
- No reusable retry helper exists (`recorder_service._record_with_retry` and planner_service `_BACKOFF_STEPS` are domain-specific, minute-scale). No tenacity dependency.

## Goals / Non-Goals

**Goals:**
- Absorb second-scale Open-Meteo blips within one planner run.
- Keep worst-case added delay small and bounded.

**Non-Goals:**
- Changing fallback semantics, caching, or planner-level backoff.
- Retrying other providers (Nordpool, HA).
- Honouring Retry-After headers (library does not expose them).

## Decisions

1. **Small in-repo helper, no dependency.** New module `backend/core/open_meteo_retry.py` with `async retry_async(fn, *, label, is_transient)` and sync `retry_sync(fn, *, label, is_transient)`, sharing constants `MAX_ATTEMPTS = 3`, `BACKOFF_S = (2.0, 4.0)`. Alternative: tenacity - rejected (new dependency). `ml/` already imports from `backend/` (e.g. `ml/forward.py`), so `ml/weather.py` can import the helper.
2. **Explicit transient classifiers.** PV: `OpenMeteoSolarForecastConnectionError`, `OpenMeteoSolarForecastRatelimitError`, `aiohttp.ClientResponseError` with status >= 500 or 429, `aiohttp.ClientConnectionError`, `asyncio.TimeoutError`. Weather: `requests.ConnectionError`, `requests.Timeout`, `requests.HTTPError` with status >= 500 or 429. Everything else (Config/Auth/Request(400)/InvalidModel, base error, 4xx) is permanent. Check Ratelimit before its RequestError parent.
3. **Per-array retry scope.** Wrap only the per-array `async with OpenMeteoSolarForecast(...)` + `estimate()` block in a coroutine passed to `retry_async`, so a new session is used per attempt and prior arrays' results in `summed_watts` are kept.
4. **Fixed short backoff, no jitter.** 2 s then 4 s = 6 s max sleep (< 10 s cap in spec). Single-instance client, so jitter adds no value.
5. **Logging.** WARNING per retry: `"Open-Meteo %s failed (attempt %d/%d): %s; retrying in %.0fs"`. Final failure re-raises the last exception unchanged so existing error recording/fallback paths are untouched.
6. **Weather sync sleep (settled).** `ml/weather.py` is synchronous; `retry_sync` uses `time.sleep`. Async callers already go through `async_get_weather_series`, which runs the fetch via `asyncio.to_thread`, so the retry wait does not block the event loop. Accepted time cap: 3 attempts, 2 s/4 s waits, worst case ~3x timeout + 6 s per request.

## Risks / Trade-offs

- [Worst-case latency: 3 attempts x timeout + 6 s per array] -> few arrays in practice; cap documented; persistent outages fail in < ~30 s.
- [Retrying 429 may worsen rate limiting] -> only 2 extra requests with backoff; acceptable.
- [Tests sleeping for real] -> helper takes injectable `sleep` / monkeypatched constants so tests run instantly.

## Migration Plan

Pure code change; deploy normally. Rollback by reverting the commit.
