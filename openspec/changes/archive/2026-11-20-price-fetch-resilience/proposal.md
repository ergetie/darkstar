# Proposal

## Why

A failed Nordpool fetch leaves the planner without prices and with a misleading error. `get_nordpool_data` catches everything and returns `[]` (`backend/core/prices.py:136-141`), uses 10 s timeouts with no retry (`:70`, `:87`) and has no last-good fallback (cache is only set on success, TTL 3600 s, `:134`). Today's and tomorrow's fetches share one `try` (`:61-135`), so after 13:00 a failed tomorrow fetch throws away today's prices that were already fetched. After 13:00 with tomorrow missing the cache is dropped on every call (`:46-47`), so each caller waits up to 20 s. Empty prices then crash the planner with `IndexError` at `planner/pipeline.py:1736` before pre-flight can raise `PRICES_UNAVAILABLE` (`planner/preflight.py:199-209`); the crash is classified `UNKNOWN` (`backend/services/planner_service.py:349-355`), so the planner retries on a flat 60 s instead of the transient backoff `[60, 120, 240, 300]` (`:28`) and shows raw exception text instead of the price hint. A fault-injection test hides this with `except Exception: pass` (`tests/fault_injection/test_price_degradation.py:41-46`).

## What Changes

- Keep today's prices when the tomorrow fetch fails or returns nothing.
- Add a last-good fallback of published Nordpool prices, persisted to disk so it survives restarts, used only for slots that have not ended yet.
- Add a 5-minute negative cache after a failed or empty tomorrow fetch so callers stop refetching on every call.
- Make `generate_schedule` raise `PlannerError(PRICES_UNAVAILABLE)` when there are no price slots, so the transient backoff and the price hint apply.
- Replace the swallowing `except Exception: pass` in the fault-injection test with an assertion on that error.
- No config keys, schema, API or UI changes. Fallback slots keep `price_source: "nordpool"` (they are real published prices); staleness is logged.

## Capabilities

### New Capabilities
- `price-fetch-resilience`: how the price feed behaves when Nordpool fetches fail, are slow or return partial data (partial results, last-good fallback, negative cache).

### Modified Capabilities
- `planner`: adds a requirement that empty price input fails with `PRICES_UNAVAILABLE` before any other planning step.

## Impact

- `backend/core/prices.py` (fetch split, last-good store, negative cache), `.gitignore` (new runtime file), `planner/pipeline.py` (guard), tests: `tests/test_nordpool_timeout.py`, new `tests/core/test_prices_resilience.py`, `tests/fault_injection/test_price_degradation.py`, `tests/conftest.py` (isolation fixture).
- New runtime file `data/nordpool_last_good.json` (git-ignored). No new dependency.
- Out of scope: GitHub issue #8 items (price reserve flapping, missing 00:00 slot, benchmark, inverter reverts) and any notification feature.
