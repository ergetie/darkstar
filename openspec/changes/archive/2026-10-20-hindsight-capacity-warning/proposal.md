# Proposal

## Why

The battery hindsight benchmark excludes any day whose implied battery capacity differs from configuration (`capacity_mismatch`). A user with a real 64 kWh battery gets every day excluded because the per-slot capacity estimate is biased low for large batteries with coarse SoC steps and slow power, so hindsight shows nothing. No capacity estimate from recorded flows is reliable enough to justify throwing a day away.

## What Changes

- Capacity mismatch no longer excludes a day. The day is scored normally and the stored record carries a non-blocking `capacity_mismatch` warning with configured and implied capacity.
- Implied capacity is estimated once over the whole multi-day history window from aggregate stored energy versus aggregate SoC movement, instead of filtering individual 15-minute slots. Tolerance is loosened because the check is advisory only.
- Per-day records gain a `warnings` list; API totals gain warning counts (`by_warning`). Existing fields are unchanged.
- The Grid & Financial "DS vs hindsight" ⓘ shows a simple warning line for affected days alongside the result, instead of listing them as not scored.
- `BENCHMARK_VERSION` is bumped so the last 14 days are re-scored on the next run/startup. Days older than the 14-day window are not recovered.
- Hindsight shows data with a simple note instead of silently dropping days (follow-up fixes from a real user's data, see design.md decisions 6-10):
  - EV charging only blocks hindsight battery discharge above 20 W average over the slot, so EV sensor idle noise (~0.3 W) no longer makes net-discharge days infeasible (`failed`).
  - Records store the day's stored-energy change and totals sum it; when a period has no score because the battery ended fuller (grid-charged for the next day), the row explains it instead of showing only missed kr.
  - Up to 4 unverified recording slots per day (including the start-SoC slot) no longer exclude the day; it is scored with an `unverified_slots` warning and count. More than 4 stays `not_clean_recording`.
  - A day slot where Darkstar recorded nothing (missing energy and/or SoC, prices present) counts as an unverified slot within the same limit; its missing energy is treated as 0 kWh on both sides. Missing prices or a missing start SoC still exclude the day as `missing_values`.
  - Initial or modelled terminal stored energy outside [0, capacity] is clamped and the day scored with a `stock_clamped` warning instead of `stock_out_of_range`.
- Remaining exclusion reasons are reviewed in design.md and left unchanged.

## Capabilities

### New Capabilities

### Modified Capabilities
- `daily-battery-benchmark`: capacity mismatch becomes a non-blocking warning computed over the whole history window; a few unverified slots and out-of-range stock become warnings; EV charging needs a 20 W slot average to block discharge; stored-energy change is recorded and explained in the card; API and card show warnings; version bump re-scores the window.

## Impact

- `backend/battery_benchmark.py` (`implied_capacity`, `benchmark_day`, `base_record`, `summarize`, `BENCHMARK_VERSION`)
- `backend/services/benchmark_service.py` (no logic change expected; version bump drives re-scoring)
- `backend/api/routers/energy.py` `get_battery_benchmark` (returns new fields via stored records and `summarize`)
- `frontend/src/lib/api.ts` types/validation, `frontend/src/components/CommandDomains.tsx` hindsight panel
- Tests: `tests/backend/test_battery_benchmark.py`, `frontend/src/components/CommandDomains.test.tsx`
- No schema change (records are JSON in `system_state`), no new dependencies.
