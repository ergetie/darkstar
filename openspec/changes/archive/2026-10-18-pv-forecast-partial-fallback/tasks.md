## 1. Fallback logic

- [x] 1.1 In `_get_stored_openmeteo_pv_for_slots` (backend/core/forecasts.py) fill missing slots from latest same-time-of-day stored value; return estimated count; return `None` if any slot cannot be filled
- [x] 1.2 Update the except block (~:518) to use the count, recompute daily totals, and log a warning with N

- [x] 1.3 Guard zero-PV defaults: `.get(rounded_time, 0.0)` (forecasts.py:510) and `else 0.0` (:582) must not silently produce 0 for missing slots on either path; a slot absent from a successful response is filled like a fallback slot and counted as estimated
- [x] 1.4 Treat an empty Open-Meteo estimate (`if solar_data_dict:` falsy, forecasts.py:488) as a failure routed to the fallback
- [x] 1.5 Return the estimated slot indices from `_get_forecast_data_async` (`pv_estimated` flag per slot); for estimated slots set `openmeteo_pv_forecast_kwh` to None in the slot dicts so `store_forecasts` (store.py:463-466, COALESCE) cannot persist them as baselines
- [x] 1.6 ml/forward.py: `_fetch_openmeteo_baseline_series` (:201-221) must stop returning `pd.Series(0.0)` on exception; propagate `PVForecastError` so `generate_forward_slots` aborts before `store_forecasts` (:674) and keeps the previous Aurora rows; estimated slots must be written with a None `openmeteo_pv_forecast_kwh` (:659); fix the trailing `values.extend([0.0] ...)` (:~222) the same way
- [x] 1.7 Fallback lookup window: 14 days before the first price slot to horizon end (module constant)

## 2. Health reporting

- [x] 2.1 Record the degraded error with `estimated_slots` and `total_slots` in context
- [x] 2.2 Update `check_forecast` (backend/health.py:962-970, currently generic "PV forecast experiencing issues") to read `last_errors[-1].context` and show "API unreachable — using last known forecast (N slots estimated)"
- [x] 2.3 Same function: severity critical when `estimated_slots / total_slots` > 0.5 (module constant), else warning; status stays "degraded"

## 3. Tests (tests/ml/test_forecast_aggregation.py)

- [x] 3.1 Full coverage: values used, 0 estimated
- [x] 3.2 Partial coverage: missing slots filled from same time-of-day, count correct, status degraded
- [x] 3.3 No coverage: `PVForecastError` raised and critical error recorded (keep existing test)
- [x] 3.5 Missing slot on partial path is never silently 0 (test for the guards in 1.3)
- [x] 3.6 Banner severity is warning at <=50% estimated and critical above
- [x] 3.7 Empty Open-Meteo estimate goes to fallback; a missing slot on a successful response is not 0 (tests/ml/test_forecast_aggregation.py)
- [x] 3.8 ml/forward.py: on `PVForecastError` no forecasts are stored and existing rows are untouched; estimated slots are not persisted as baselines (tests/ml/test_aurora_forward.py)
- [x] 3.9 Executor default `max_schedule_age_hours` is 2 (see 4.3)
- [x] 3.4 Health banner text includes N

## 4. Stale-schedule age default (2 h)

- [x] 4.1 executor/config.py:340 change `max_schedule_age_hours: int = 6` to 2 and the `executor_data.get("max_schedule_age_hours", 6)` default at :1095 to 2
- [x] 4.2 Confirm `config.default.yaml:399` already says 2 (verified; no change)
- [x] 4.3 Update tests asserting 6: tests/executor/test_executor_safety.py (`_make_engine` default :69, explicit 6 at :296/:333/:355, default assertion and docstring :390-393 now expect 2); other tests use `config.max_schedule_age_hours + 1` and need no change
- [x] 4.4 Apply the executor spec MODIFIED delta (specs/executor/spec.md in this change)

## 5. Planner DB forecast path (build_db_forecast_for_slots)

- [x] 5.1 Fill slots without a stored row from same time-of-day (shared `_estimate_from_same_time_of_day`), lookback 14 days, instead of carrying the last stored slot / defaulting to 0
- [x] 5.2 Keep linear interpolation for 1-2 slot interior gaps (`_interpolate_small_pv_gaps`)
- [x] 5.3 Flag `pv_estimated`, count and report degraded via `record_forecast_error`; no stored rows (fresh install / learning period) is logged at info level only and records no health error
- [x] 5.4 Tests (tests/ml/test_db_forecast_gap_fill.py): long outage day 4+ daytime non-zero, earlier-than-first-row slots, small gap, no rows, reporting

## 6. Verify

- [x] 6.1 Run `./scripts/lint.sh` and the forecast tests
