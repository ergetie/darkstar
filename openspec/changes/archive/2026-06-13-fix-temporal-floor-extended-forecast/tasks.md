## 1. Emit extended slot-level forecasts from the forecast builder

- [x] 1.1 In `backend/core/forecasts.py::_get_forecast_data_aurora()`, within the existing `extended_records` loop (currently building daily aggregates), also append a slot-level entry per record to a new `extended_slots` list: `start_time` (tz-aware, normalized the same way as the daily loop), `pv_forecast_kwh`, `load_forecast_kwh`, and `pv_p10`/`pv_p90`/`load_p10`/`load_p90` where present.
- [x] 1.2 Reuse the rows already fetched at `get_forecast_slots(start_dt, end_dt, active_version)` — do NOT add a second DB query.
- [x] 1.3 Apply the same load-fallback rules used for the daily loop (HA profile when `aurora_load_enabled` is false or `base_load <= 0.001`) so extended slot loads are consistent with the daily totals.
- [x] 1.4 Add `"extended_slots": extended_slots` to the dict returned by `_get_forecast_data_aurora()`.

## 2. Thread the extended slots through to the planner pipeline

- [x] 2.1 In `backend/core/forecasts.py` (the planner-input builder, lines 653-669): after `forecast_data = forecast_result.get("slots", [])` (line 654), add `extended_forecast_data = forecast_result.get("extended_slots", [])`.
- [x] 2.2 Add `"extended_forecast_data": extended_forecast_data` to the dict returned at lines 661-669 (alongside `forecast_data` / `daily_pv_forecast` / `daily_load_forecast`).

## 3. Feed the safety floor from the extended slots

- [x] 3.1 In `planner/pipeline.py` (~line 445), build `full_forecast_df` from `input_data["extended_forecast_data"]` instead of `input_data["forecast_data"]`.
- [x] 3.2 If `extended_forecast_data` is missing/empty, fall back to `input_data["forecast_data"]` so behavior degrades to today's (preserves the genuine-outage path).
- [x] 3.3 Confirm `price_horizon_end` continues to be derived from the price-bounded `df` (unchanged) and that `calculate_safety_floor()` needs no signature change.

## 4. Verify behavior

- [x] 4.1 With `slot_forecasts` populated beyond the price horizon, confirm a plan run computes `using_extended_data = True` and does NOT log "Extended forecast data unavailable or insufficient".
- [x] 4.2 Confirm that with extended slots absent/empty, the fallback still fires and logs the warning (genuine-absence path unchanged).
- [x] 4.3 Confirm the Kepler planning horizon, price loading, and schedule slot count are unchanged (no regression to the optimization window).
- [x] 4.4 Validate on a representative short-horizon / winter-style case that the safety floor reflects the overnight temporal deficit beyond the price horizon and remains within the `max_safety_buffer_pct` cap.

## 5. Tests

- [x] 5.1 Unit test: `_get_forecast_data_aurora()` returns `extended_slots` covering ≥ 24h beyond the price horizon when the store has the rows, with correct per-slot pv/load values.
- [x] 5.2 Unit/integration test for `calculate_safety_floor()`: given a `full_forecast_df` extending past `price_horizon_end`, it computes the temporal deficit over the 24h look-ahead window and sets `using_extended_data = True` (no warning).
- [x] 5.3 Regression test: empty/absent extended data → fallback path logs the warning and uses the available horizon.
- [x] 5.4 Run `scripts/ci_local.sh` (or the project's standard check) and ensure all checks pass.
