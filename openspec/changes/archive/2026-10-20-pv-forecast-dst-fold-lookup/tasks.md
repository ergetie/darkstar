# Tasks

## 1. Canonical slot key

- [x] 1.1 Add a helper in `backend/core/forecasts.py` that maps any aware datetime/pandas Timestamp (naive treated as UTC) to int Unix seconds floored to 900 s
- [x] 1.2 In `_get_forecast_data_async`, build a `{key: watts}` index from `solar_data_dict` once and look up slots by key; remove the `.replace(minute=...)` rounding and the incorrect "aware datetimes hash by UTC instant" comment
- [x] 1.3 In `_get_stored_openmeteo_pv_for_slots`, key `by_slot` and the exact lookup with the same helper (keep `slot_times` local for dates/time-of-day)
- [x] 1.4 In `build_db_forecast_for_slots`, key `indexed` and the `indexed.get(...)` lookup with the same helper (keep local datetimes for `sorted_stored` and time-of-day use)

## 2. Tests

- [x] 2.1 Regression: slots from `dst_safe_date_range` (Europe/Stockholm) spanning 2026-10-25 vs fixed-offset (+02:00) watts keys covering every instant; assert no estimated slots, `record_forecast_error` not called, `clear_forecast_errors` called
- [x] 2.2 Spring-forward sanity (2026-03-29) with the same setup; assert all slots matched
- [x] 2.3 Stored fallback: baseline in the fold hour matches a fold=1 pandas Timestamp slot exactly (not estimated), in both `_get_stored_openmeteo_pv_for_slots` and `build_db_forecast_for_slots`
- [x] 2.4 Existing mapping/perf tests still pass; run `./scripts/lint.sh`
