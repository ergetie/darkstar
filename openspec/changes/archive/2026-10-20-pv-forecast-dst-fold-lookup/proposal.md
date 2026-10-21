# Proposal

## Why

Every run between roughly Oct 18 and Oct 25 users see "Open-Meteo forecast incomplete — using last known forecast (4 slots estimated)" although Open-Meteo returned complete data. The live slot mapping in `_get_forecast_data_async` (`backend/core/forecasts.py`) looks up each price slot's rounded `start_time` directly in the dict of `estimate.watts` keys. Slot times are often pandas Timestamps from `dst_safe_date_range` (Europe/Stockholm); keys are fixed-offset python datetimes. For the repeated autumn hour (e.g. 2026-10-25 02:00–02:45 +01:00, fold=1) the pandas Timestamp hash differs from the datetime key for the same instant, so the lookup misses. Reproduced on prod: exactly those 4 slots miss. The result is `incomplete_response=True` every run while the fold hour is in the 7-day horizon, so `record_forecast_error` fires and `clear_forecast_errors` never runs. Plans are unaffected (fallback fills ~0 night PV); only the banner and logs are wrong.

## What Changes

- Match live Open-Meteo PV keys and price slot times by a canonical UTC key (integer Unix seconds of the 15-minute-floored instant) instead of relying on aware-datetime hashing.
- Apply the same canonical key to the stored-baseline exact-slot lookup in `_get_stored_openmeteo_pv_for_slots` (`by_slot`), which has the same mixed pandas/pytz key pattern, and to the DB forecast fallback lookup in `build_db_forecast_for_slots` (`indexed`), which fails the same way.
- Remove the incorrect comment claiming aware datetimes match across zones.
- Add regression tests for the October fold hour and a spring-forward sanity case.

## Capabilities

### New Capabilities

### Modified Capabilities
- `open-meteo-pv-forecast`: "Efficient Live PV Slot Mapping" now requires matching by UTC instant regardless of datetime type or DST fold, with missing slots estimated (not 0.0); new requirement that stored-baseline exact matching is instant-based too.

## Impact

- `backend/core/forecasts.py` (`_get_forecast_data_async` slot mapping, `_get_stored_openmeteo_pv_for_slots`, `build_db_forecast_for_slots`).
- Tests under `tests/` for forecasts. No API, schema, config or dependency changes.
