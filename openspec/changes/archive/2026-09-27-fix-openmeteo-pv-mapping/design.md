## Context

`_get_forecast_data_async` fetches Open-Meteo PV for each configured array, sums watts per timestamp into `solar_data_dict`, then for each price slot scans `solar_data_dict.items()` until a key equals the slot time. Keys are fixed-offset aware datetimes from the library; slots are pytz-aware pandas Timestamps, so each comparison normalises timezones (4.5M `pytz.utcoffset` calls in one prod run).

`OpenMeteoSolarForecast` defaults to `past_days=92`. Prod receives 7,830 entries starting ~66 days back, so each slot scans ~6,600 stale entries before matching. Evidence:

| Environment | Entries | Current mapping | Direct lookup | Identical |
|---|---|---|---|---|
| Local, prod-shaped | 7,830 | 4.0 s | 9 ms | yes |
| Prod, real data | 7,830 | 33.5 s | 7 ms | yes |

## Goals / Non-Goals

**Goals:**
- Slot mapping cost independent of series length.
- Live fetch downloads only usable history.
- Byte-identical `pv_forecast_kwh` / `openmeteo_pv_forecast_kwh` for the same inputs.

**Non-Goals:**
- Caching or persisting live forecasts (ML history already has a DB-backed backfill with missing-slot detection).
- Changing the dashboard hindcast path, the backfill path, or other O(n) loops in `ml/forward.py` (measured at ~0.1 s).
- Explaining why Open-Meteo returns ~66 rather than 92 past days (irrelevant once `past_days=1`).

## Decisions

1. **Direct lookup `solar_data_dict.get(rounded_time, 0.0)`.** Aware datetimes and Timestamps hash and compare by UTC instant, so a dict lookup finds the same key the scan found, including across fixed-offset vs pytz zones. Verified identical on prod data. Alternative: pandas reindex — rejected as heavier and changes types for no gain.
2. **`past_days=1`, not 0.** Callers pass planner/price slots starting at today 00:00 at the earliest; one past day guarantees coverage across midnight and timezone offsets at negligible cost (~2 days vs ~66). Alternative `past_days=0` — saves little and risks missing an early slot near midnight.
3. **Keep `forecast_days` at library default.** Horizon needs are unchanged; out of scope.

## Risks / Trade-offs

- [A slot key's timestamp has non-zero nanoseconds and fails hash equality] → Slots are rounded to 15-min boundaries with seconds/microseconds zeroed before lookup, as today.
- [`daily_pv_forecast` now covers fewer past days] → Consumers read today onward (4-day forward fill from first slot date); verify no consumer reads days before yesterday.
- [Open-Meteo rejects `past_days=1` combination] → Same parameter is already used by `ml/weather.py` and the backfill path.

## Migration Plan

Code-only; ships with the next release. Rollback = revert the commit.
