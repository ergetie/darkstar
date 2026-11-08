# Tasks

## 1. Never-blank error descriptions

- [x] 1.1 Add `describe_exception` in `backend/core` (type plus text, `repr` fallback when text is empty, length capped) with unit tests for `httpx.ReadTimeout`, `asyncio.TimeoutError`, `aiohttp.ServerTimeoutError`, an exception with text, and a very long message. Verify the tests pass.
- [x] 1.2 Use it in `get_power_history_batch`, the broad `except` in `get_load_profile_from_ha`, the Open-Meteo retry log, and `executor/actions.py` `_retry_with_backoff` (retry log and `HACallError` detail). Tests with `caplog`: the history log for a read timeout names `ReadTimeout`; the executor retry log for `asyncio.TimeoutError` names `TimeoutError` and does not match `attempt 1/4): \.`; the final `HACallError` message contains the last exception's description.

## 2. Retry and timeout for load-profile history chunks

- [x] 2.1 Generalise `retry_async` in `backend/core/open_meteo_retry.py` with optional attempts and backoff arguments (defaults unchanged) and confirm the existing Open-Meteo retry tests still pass.
- [x] 2.2 Add an httpx-aware transient classifier (timeouts, connect/network errors, remote protocol error, 5xx, 429 transient; other 4xx permanent) with parametrised tests.
- [x] 2.3 Give `get_power_history_batch` an opt-in `attempts` argument (default 1; `timeout` already exists as positional `float = 12.0`, so only widen its type to `float | httpx.Timeout`) and verify the recorder, water progress and backfill callers are untouched with a test asserting the default call count is one.
- [x] 2.4 In `get_load_profile_from_ha` use 3 attempts, backoff 1 s then 3 s, connect 5 s / read 20 s capped by a 60 s overall deadline, and abort after two consecutive exhausted chunks. Tests with the `_FakeHA` pattern in `tests/backend/test_ha_client_load_profile.py` (inject sleep and clock; do not assume gap-free points, since unavailable states now end the hold and fixtures may contain them): timeout once then success gives the full 7-day profile; permanent 401 is attempted once; a stalled HA stops at the deadline; two exhausted chunks abort the loop.

## 3. Partial window and last good profile

- [x] 3.1 Depends on the per-slot coverage averaging already in `get_load_profile_from_ha` (`_coverage_averaged_profile`); do not add a divide-by-days-fetched step. A failed day chunk adds no energy and no covered seconds, and the days-fetched count is only used for the floor of `ceil(7/2)` days; fewer days is a transient failure. Tests: 6 of 7 days equals the mean of those six (also when a fetched day has an unavailable gap) and is not scaled by 6/7; 3 of 7 falls through to the next fallback.
- [x] 3.2 Add the last good profile store (module variable plus `data/load_profile_last_good.json` via `write_json_atomic`) with validation (sensor match, version, 96 finite non-negative values, `0 < total <= 500`, timestamp not in the future, age at most 7 days). Tests with `tmp_path`: round trip, restart simulation, stale, other sensor, corrupt JSON, future timestamp, disk write failure ignored.
- [x] 3.3 Wire the fallback order (full, partial, last good, synthetic/demo) for transient failures only. Tests: all chunks fail with a good profile stored returns it; empty history and the 500 kWh/day case still return the demo or synthetic profile and never the stored one; a configured `synthetic_daily_load_kwh` does not outrank a valid stored profile on transient failure.
- [x] 3.4 Add `data/load_profile_last_good.json` to `.gitignore` and verify `git status` shows it untracked-ignored after a test run.

## 4. Failure memo and shared in-flight build

- [x] 4.1 Add the memo (sensor, monotonic failure time, `threading.Lock`), the 300 s cooldown constant and the per-loop in-flight task, plus a `force_refresh` keyword on `get_load_profile_from_ha`; `backend/api/routers/debug.py` passes `force_refresh=True`. Verify by tests with injected clock and the `_FakeHA` pattern.
- [x] 4.2 Tests: after an all-chunks-fail build, a second call within the cooldown makes zero history requests and returns the stored (else synthetic/demo) profile with the matching status; after the cooldown one new build runs; success clears the memo; a different sensor ignores it; `force_refresh` bypasses it; empty history and implausible data do not set it.
- [x] 4.3 Coalescing test: two or three concurrent calls in one loop produce one set of history requests and equal results; the in-flight entry is removed after success and after failure (including cancellation).
- [x] 4.4 Outage cost test: with a stalled fake HA and ten calls inside one cooldown window, total simulated request time is at most one deadline (60 s), and the planner-run shape (two calls plus one API call) makes one build.

## 5. Truthful health status

- [x] 5.1 Add `stale` and `partial` reasons to `backend/health.py` (`check_load_forecast` messages and severities) and a narrow clear for statuses set by the HA path. Tests: stored profile shows age and sensor and never "demo" or "0.5 kWh flat"; partial shows `N of 7 days`; a full live build clears `stale`/`partial`/`demo` but leaves `baseline` and `no_ml`; `ml/forward.py` behaviour unchanged.
- [x] 5.2 Update the existing demo-message tests in `tests/backend/test_ha_client_load_profile.py` only where the new fallback order changes the outcome, and confirm the discard-reason messages from `load-history-sanitization` still pass.

## 6. Integration

- [x] 6.1 Run `UV_NO_SYNC=1 uv run python -m pytest tests/backend/test_ha_client_load_profile.py tests/test_inputs_ha_client.py tests/backend/test_ha_client_power_integration.py` plus the executor action tests and the Open-Meteo retry tests, then `./scripts/lint.sh`; all pass.
- [x] 6.2 Confirm `openspec validate load-profile-fetch-resilience --strict` passes and no production file or database was touched.

## Workflow follow-up

- Archive the change after review.
- [x] Follow-up done: the remaining `except Exception as e: ... %s` sites in `executor/actions.py` (and other HA/network handlers) use `describe_exception`.
- [x] Follow-up done: the load profile uses the configured `timezone` instead of a hard-coded `Europe/Stockholm`.
