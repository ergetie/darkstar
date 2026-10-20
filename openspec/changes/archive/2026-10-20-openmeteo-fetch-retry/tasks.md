# Tasks

## 1. Retry helper

- [x] 1.1 Create shared retry helper (`retry_async` / `retry_sync`, `MAX_ATTEMPTS=3`, backoff 2 s/4 s, injectable sleep, WARNING log per retry, re-raise last error); at `backend/core/open_meteo_retry.py`. Verify: unit tests in 1.3 pass.
- [x] 1.2 Add transient classifiers: `is_transient_pv_error` (ConnectionError, RatelimitError, aiohttp ClientResponseError 5xx/429, ClientConnectionError, asyncio.TimeoutError) and `is_transient_http_error` for requests (ConnectionError, Timeout, HTTPError 5xx/429). Verify: parametrized tests classify 400/401/403/422/InvalidModel/base error as permanent.
- [x] 1.3 Unit tests for helper: transient-then-success returns result after 2 calls; persistent transient stops after 3 calls and raises last error; permanent error makes 1 call; retries logged at WARNING. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/test_open_meteo_retry.py -v`.

## 2. PV forecast integration

- [x] 2.1 In `backend/core/forecasts.py` `_fetch_forecast()`, wrap each per-array `OpenMeteoSolarForecast(...)` + `estimate()` in `retry_async` with label `PV array <i>`, keeping already-summed arrays. Verify: tests in 2.2.
- [x] 2.2 Tests (mock `OpenMeteoSolarForecast`, zero sleep): array 2 fails once with ConnectionError then succeeds -> array 1 called once, array 2 twice, no fallback, no PVForecastError; all attempts fail -> stored-estimate fallback used (and PVForecastError when no stored data); ConfigError -> one attempt then fallback. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/ -k "openmeteo and retry" -v`.

## 3. Weather fetch integration

- [x] 3.1 In `ml/weather.py`, wrap `requests.get` + `raise_for_status()` in `retry_sync` with label `weather`; keep existing final except/empty-DataFrame path. Verify: tests in 3.2.
- [x] 3.2 Tests (monkeypatched `requests.get`, zero sleep): 503 then 200 -> populated frame; persistent 503 -> 3 calls, empty frame; 400 -> 1 call. Verify: `UV_NO_SYNC=1 uv run python -m pytest tests/weather -v`.

## 4. Verification

- [x] 4.1 Run `./scripts/lint.sh` and the full forecast/weather test suites; all pass.
