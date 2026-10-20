# Proposal

## Why

Open-Meteo returned intermittent 503 Service Unavailable responses on 16-19 Oct 2026. Most outages lasted seconds, yet with no retry anywhere each one failed the whole PV fetch (falling back to stored estimates or raising PVForecastError) and emptied the weather frame until the next planner run ~30 minutes later.

## What Changes

- Add a short, bounded retry with backoff (3 attempts, ~2 s then ~4 s, total retry wait capped) to Open-Meteo HTTP requests.
- Retry only transient failures: connection errors, timeouts, HTTP 5xx and 429. Never retry 4xx configuration/auth/request errors or malformed responses.
- PV forecast (`backend/core/forecasts.py`): retry each per-array `estimate()` call individually so a single failed array does not refetch the arrays that already succeeded.
- Weather fetch (`ml/weather.py`): retry the `requests.get` call with the same policy.
- Log each retry at WARNING with attempt number, delay and error; the forecast error and stored-estimate fallback happen only after retries are exhausted.
- No new dependencies.

## Capabilities

### New Capabilities
- `open-meteo-fetch-retry`: bounded retry policy for transient Open-Meteo failures (PV and weather fetches), classification of transient vs permanent errors, and logging/fallback ordering.

### Modified Capabilities

## Impact

- Code: `backend/core/forecasts.py` (`_get_forecast_data_async` / `_fetch_forecast`), `ml/weather.py` (Open-Meteo fetch), new small retry helper module (e.g. `backend/core/open_meteo_retry.py`).
- Planner latency: worst case adds the capped retry budget (~6 s of sleep plus request timeouts) per failing request.
- Tests: new unit tests for retry, fallback and non-retry paths.
- No API, config or DB changes.
