## 1. Known-price resolver

- [x] 1.1 Tag entries in `get_nordpool_data` / `_process_nordpool_data` with `price_source` (`"nordpool"` for real entries, `"forecast"` for D+1 fallback entries)
- [x] 1.2 Add `get_known_spot_by_slot(config)` in `backend/core/prices.py`, returning tz-aware local slot start → raw spot SEK/kWh for `"nordpool"` entries only; on fetch failure, log a warning and return an empty map
- [x] 1.3 Unit tests: fallback entries excluded; known entries returned; fetch failure → empty map + warning

## 2. Planner price-floor inputs

- [x] 2.1 `fetch_price_floor_inputs`: await the resolver, then pass the known map into `_fetch_price_floor_inputs_sync`
- [x] 2.2 `_fetch_price_floor_inputs_sync`: merge per slot (known wins, else latest-issue `spot_p50`, including slots with no forecast row), keep the offset-0 `slot_start >= now` filter, normalize timestamps to local tz
- [x] 2.3 Add per-day known/forecast slot counts to the EV multi-day quota log line
- [x] 2.4 Regression test reproducing 2026-09-24: stale cheap forecast for today and published ≈2.0 SEK → today is not the largest quota
- [x] 2.5 Tests: D+1 published prices used after the auction; DST-boundary key merge; safety-floor addon with a known-price day

## 3. Daily outlook

- [x] 3.1 `get_daily_outlook`: accept an optional known-spot map and merge per slot (p10/p50/p90 = known for known slots)
- [x] 3.2 Supply the resolver map from both callers: `async_get_daily_outlook` (outlook router) and `backend/api/routers/analyst.py` (Aurora advisor)
- [x] 3.3 Tests: D+1 published overrides forecast; unpublished days unchanged

## 4. Verification

- [x] 4.1 Run `./scripts/lint.sh` and the full test suite
- [x] 4.2 Replay prod inputs from 2026-09-24 23:00 read-only and confirm the new quota split pushes energy toward Sat/Sun
