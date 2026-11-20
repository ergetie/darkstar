# Design

## Context

See proposal.md for the problem. Current behaviour in `backend/core/prices.py`: `get_nordpool_data` reads a 1 h TTL in-memory cache (`cache_sync`, key `NORDPOOL_CACHE_KEY`), then fetches today (`:63-71`) and, after 13:00, tomorrow (`:78-93`) inside one `try` (`:61-141`) whose handlers return `[]`. `TTLCacheSync.get` deletes expired entries (`backend/core/cache.py:49-56`), so nothing survives expiry. Callers: planner input (`backend/core/forecasts.py:850`), schedule/forecast/analyst/readiness/recorder endpoints, `get_known_spot_by_slot`. `price_source` already exists on every processed slot (`"nordpool"` or `"forecast"`, `prices.py:301`) and drives the chart's "estimated" marker (`frontend/src/components/ChartCard.logic.ts:141`) and `get_known_spot_by_slot`. Precedent for a persisted last-good file: `data/load_profile_last_good.json` (`backend/core/ha_client.py:1211`). `backend/core/atomic_json.py::write_json_atomic` exists.

## Goals / Non-Goals

**Goals:**
- Never lose already-fetched prices to a later failure in the same call.
- Keep planning possible through a Nordpool outage for the slots that are still ahead.
- Bound the cost of a missing tomorrow, or of a total outage, to one fetch attempt per 5 minutes across all callers.
- Make empty prices produce `PRICES_UNAVAILABLE` (transient backoff, price hint).

**Non-Goals:**
- Retries inside one call (the planner service already retries with backoff).
- Changing timeouts, the forecast fallback before 13:00, notifications, UI, config keys, DB schema, docs.
- Anything from GitHub issue #8 (`ml/price_features.py`, `ml/price_forecast.py`, `planner/strategy/price_reserve.py`).

## Decisions

1. **Split the fetch.** A helper `_fetch_day(client, day, area, resolution, local_tz)` returns the day's raw values or raises. Today and tomorrow are fetched in separate `try` blocks (the existing `asyncio.wait_for(..., 10.0)` stays). A tomorrow failure is logged and treated as "no tomorrow values"; it never discards `today_values`. A today failure leaves `today_values` empty and falls through to the last-good fallback. When today's fetch fails, tomorrow's fetch is skipped (Nordpool is unreachable, a second attempt would only add a timeout). Alternative (one shared try with partial variables) rejected: harder to test and keeps the coupling.

2. **Last-good store holds raw entries, persisted to disk and mirrored in memory.** File `data/nordpool_last_good.json` (git-ignored, written with `write_json_atomic` via `asyncio.to_thread`), content: `{price_area, currency, resolution_minutes, saved_at, entries: [{start, end, value}]}` with ISO timestamps and `value` in SEK/MWh, only `nordpool`-source entries (never forecast-fallback entries). Persisted rather than memory-only because the common recovery path is a container restart or updater rollback during an outage; memory-only would leave the planner with no prices exactly then. Raw entries rather than processed slots so that fees, tax, VAT and markup are applied with the current config at fallback time (the pricing-change cache invalidation in `backend/api/routers/config.py:391` then needs no matching hook). The in-memory copy avoids re-reading the file on every failed call; load from disk lazily on first use. A file that is missing, unparsable or has a mismatched area, currency or resolution is ignored (logged once at warning for corruption).

3. **When to write.** Only after a complete fetch: today non-empty and, when `now.hour >= 13`, tomorrow non-empty. An incomplete fetch never overwrites a better stored set. Stored entries whose `end` is more than 1 day in the past are dropped on write (file stays under about 200 entries).

4. **Which slots the fallback may use.** Only entries with `end > now` (the running slot is included). Merge rule: fresh entries first, then stored entries whose `start` is not already present in the fresh set; `_process_nordpool_data` already sorts and dedups keeping the first occurrence, so fresh data wins. Past slots are excluded because the planner and `check_price_data` only use future slots and a past price carries no value.

5. **Interaction with the pre-13:00 forecast fallback.** Order: fresh, then stored entries, then the existing forecast fallback only when there are still no tomorrow slots and `now.hour < 13` (unchanged condition, now evaluated after the stored merge).

6. **Marking staleness: reuse `price_source`, do not add a field.** Stored slots are genuine published prices, so they keep `price_source: "nordpool"`; changing them to `"forecast"` would mislabel real prices in the chart and drop them from `get_known_spot_by_slot`. There is no existing field for fetch freshness and no new UI feature is in scope, so staleness is surfaced by logging: `warning` when a fallback starts ("using stored prices, N slots, saved <saved_at>"), `info` on repeats, reset when a fetch succeeds. A module-level flag holds that state.

7. **Negative cache: 5 minutes, for partial and total failure.** Shared constant `FETCH_RETRY_SECONDS = 300`. Reason: Nordpool normally publishes around 12:45-13:15 CET, so a late publication is picked up within 5 minutes; 300 s equals the planner's backoff cap (`_BACKOFF_STEPS`), so retries stay aligned; it limits the up-to-20 s of timeouts to at most one per 5 minutes across all callers (UI, recorder, readiness and planner would otherwise each wait up to 10 s during an outage). Mechanism: when the fetch is incomplete, i.e. `now.hour >= 13` and tomorrow is missing (failed or empty), or today's fetch failed or returned nothing (total failure), the call caches its result with `ttl_seconds=300` instead of 3600 and sets module-level `_retry_after = time.monotonic() + 300`. The result is today plus stored slots for a partial failure, and the processed stored slots (`end > now`) or `[]` for a total failure. The check at `prices.py:46-47` drops the cache only when `time.monotonic() >= _retry_after`. A complete fetch caches for 3600 s as before and resets the variable. A cached empty list must be returned as a hit (the cache check must distinguish a cached `[]` from a miss). While serving a cached total-failure result, the future-slot filter is re-applied so slots that ended since caching are not returned. The cached object is the processed list, so the stored-slot fallback is not reprocessed per call.

8. **Total failure.** If nothing could be fetched, return the processed stored slots or `[]` when none qualify, negative-cached for 300 s per decision 7. Existing `TimeoutError`/`Exception` handlers are kept only around the processing and cache step and now fall back to the stored slots too.

9. **Empty-price guard.** In `PlannerPipeline.generate_schedule`, directly after `validate_water_heating_config` (before `load_learning_overlays` and `prepare_df`), `if not input_data.get("price_data"): raise PlannerError(PlannerErrorCode.PRICES_UNAVAILABLE, details={"price_slot_count": 0, "min_required_hours": PRICE_HORIZON_MIN_HOURS})`, importing the constant from `planner/preflight.py`. Same code and details as `check_price_data`, so the transient backoff (`planner/errors.py:113-119`, `planner_service.py:28`) and the hint apply. `schedule.json` is untouched because the guard runs before any write. Alternative (call `check_price_data` early) rejected: it needs the real `now`, which is computed after `prepare_df`, and pre-flight still runs later for the horizon check.

10. **Tests.** Test isolation: an autouse fixture in `tests/conftest.py` points the store path to `tmp_path` and resets module state, so no test touches `data/`. New tests use the `patch("backend.core.prices.Prices")` pattern from `tests/test_nordpool_timeout.py` with a controlled clock, no network.

## Risks / Trade-offs

- [Stored prices expire during a long outage] -> the fallback only returns slots with `end > now`, so the horizon shrinks and pre-flight (`< 4 h`) raises `PRICES_UNAVAILABLE`, the correct outcome.
- [Stale prices look current in the UI] -> accepted, no field exists; mitigated by warning logs. Published Nordpool prices do not change after publication, so the data itself is correct.
- [Disk write failure] -> logged at warning, in-memory copy still updated; never raised.
- [A total outage still costs up to 10 s for the first call per 5 minutes] -> bounded by the negative cache; later callers get the cached result immediately.
- [Cached total-failure result outlives a recovery by up to 5 minutes] -> accepted, same cadence as the planner backoff.
- [5 min delay in noticing late tomorrow prices] -> bounded and within the planner's own backoff cadence.

## Migration Plan

None. The file is created on the first complete fetch; no file means no fallback. Rollback is reverting the commit; the file is ignored.
