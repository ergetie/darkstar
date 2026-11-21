# Tasks

## 1. Re-verify findings at HEAD

- [x] 1.1 Confirm `export_price_sek_kwh` is raw spot (`backend/core/prices.py` `calculate_import_export_prices`, `backend/recorder.py` storage) and that the `/accuracy` join compares like with like; if not, find the correct actual-spot source and fix the endpoint consistently
- [x] 1.2 Re-verify the pre-publication path: `price_horizon_end = df.index[-1]` and known window `df[df.index >= now_slot]` in `planner/pipeline.py`; forecast fallback slots tagged `price_source == "forecast"` in `get_nordpool_data` (`backend/core/prices.py`); `build_price_dataframe` drops `price_source`; `input_data["price_data"]` keeps it
- [x] 1.3 Confirm `price_forecasts` holds `days_ahead` 1-3 rows with actuals in the 7-day window (pruning keeps latest issue per `(slot_start, days_ahead)`), so horizon-matched accuracy is computable with the same join
- [x] 1.4 Confirm `forecast-slot-benchmark-and-dead-config-fixes` is implemented first and that fallback records in `input_data["price_data"]` carry `forecast_days_ahead`; if the key is missing treat the horizon as 1
- [x] 1.5 Re-check `price_reserve.py` (threshold table, `size_price_reserve`, `evaluate_price_reserve`, `PriceReserveInputs`) and `pipeline.py` `build_price_reserve_inputs` / `_log_price_reserve_event` line references still match the design

## 2. Shared accuracy function

- [x] 2.1 Create `ml/price_accuracy.py` with `fetch_accuracy_rows(db_path, days_ahead=1)` (current SQL with `days_ahead` bound; 1 reproduces today's query), `ForecastAccuracy` dataclass (`mae`, `bias`, `debiased_mae`, `sample_days`, `status`), `compute_forecast_accuracy(rows)` and `load_forecast_accuracy(db_path, days_ahead=1)`
- [x] 2.2 Switch `backend/api/routers/price_forecast.py` to the shared function; keep response shape, rounding (4 decimals) and `insufficient_data` payload identical; remove the duplicated maths and `_fetch_accuracy_rows` (update any test patching it)

## 3. Reserve logic

- [x] 3.1 Add `forecast_bias_sek_kwh`, `forecast_error_sek_kwh` (import domain) and `accuracy_fallback` to `PriceReserveInputs` with defaults that reproduce current behaviour
- [x] 3.2 In `evaluate_price_reserve` compute `effective_threshold = max(reserve_threshold_sek(risk), forecast_error)` and pass it to `size_price_reserve`; add bias, typical error, effective threshold and fallback flag (with defaults) to `PriceReserveResult` for every return path including `inactive_price_reserve`
- [x] 3.3a Add a sibling of `fetch_forecast_spot_sync` in `planner/strategy/ev_deferral.py` that returns `(spot, days_ahead)` per slot (latest issue); make the original delegate with unchanged signature/result; extend `_fetch_unseen_forecast_sync` in `pipeline.py` to return the per-slot horizon
- [x] 3.3b In `pipeline.py` derive `forecast_slot_starts` as a slot_start to `days_ahead` mapping from `input_data["price_data"]` (`price_source == "forecast"`, `forecast_days_ahead` default 1) at the call site and pass it to `build_price_reserve_inputs` (new optional argument, default empty); do not change the planner df, solver adapter or schedule prices
- [x] 3.3c In `build_price_reserve_inputs` load accuracy for the needed horizons in one `asyncio.to_thread` call; subtract each unseen slot's own-horizon bias from its spot before `spot_to_import_price`; subtract `bias_h * k` (h = the slot's carried horizon) (`k` = converter marginal factor, `1 + VAT`) from the import price of forecast-sourced known slots only (never `nordpool` slots); per-horizon fallback chain own horizon, then D+1, then no correction; set `forecast_error_sek_kwh` to the largest `debiased_mae` among used horizons scaled by `k`; on any exception (warning log) use no correction and `accuracy_fallback=True`; never set `error` for an accuracy failure
- [x] 3.4 Add `price_reserve_effective_threshold_sek`, `price_reserve_forecast_bias_sek_kwh`, `price_reserve_forecast_error_sek_kwh` and `price_reserve_accuracy_fallback`, `price_reserve_forecast_accuracy` and `price_reserve_corrected_known_slots` to `_price_reserve_debug` in `planner/strategy/s_index.py` (all present when inactive too, `price_reserve_threshold_sek` stays the base threshold)
- [x] 3.5 Include the new keys in the price-reserve strategy event details in `pipeline.py` and mention the applied bias/effective threshold in the active-event message; add the optional keys to the debug type in `frontend/src/lib/api.ts`

## 4. Tests

- [x] 4.1 `tests/planner/strategy/test_price_reserve.py`: biased forecast with small gap gives 0 reserve; same gap with accurate unbiased forecast reserves as today; large real gap above error reserves; no/insufficient accuracy data equals current behaviour exactly; boundary at the effective threshold (gain equal gives 0, just above reserves); risk 5 still gated by error
- [x] 4.2 New shared-function tests (e.g. `tests/ml/test_price_accuracy.py`), including `days_ahead` parametrisation (rows of other horizons ignored): bias sign (forecast minus actual), MAE, de-biased MAE (constant offset gives 0), unique-days count, insufficient data below 2 days, empty rows, rows outside 7 days ignored
- [x] 4.3 Agreement test: endpoint `d1_bias`/`d1_mae` equal the planner's bias/MAE for the same seeded DB
- [x] 4.4 `tests/planner/test_price_reserve_pipeline.py`: seed `price_forecasts` + `slot_observations`; assert unseen prices are de-biased, effective threshold gates the reserve, debug keys and event details are present; accuracy read error and insufficient data fall back to current behaviour and the run continues
- [x] 4.5 Pre-publication scenario (unit and pipeline): known window = real today slots plus D+1 `price_source == "forecast"` slots, unseen = D+2, both forecasts biased; assert known forecast slots and unseen slots are both corrected on the same basis, real slots untouched, a bias-only gap neither creates nor suppresses a reserve, and the solver's df prices are unchanged; post-publication scenario (known all real) behaves as before
- [x] 4.5b Time-of-day scenarios: pre-issue (known forecast slots horizon 2, unseen horizon 3), post-issue pre-publication (known horizon 1, unseen 2), post-publication (no known forecast slots, unseen 2); each uses its horizon's bias; absent `forecast_days_ahead` is treated as horizon 1
- [x] 4.6 Horizon tests: unseen slots with `days_ahead = 2` use D+2 accuracy; missing D+2 data falls back to D+1; missing both leaves slots uncorrected; the gate uses the largest de-biased MAE among used horizons
- [x] 4.7 Existing `tests/api/test_price_forecast_api.py` accuracy tests pass unchanged

## 5. Verification

- [x] 5.1 Run targeted tests: `UV_NO_SYNC=1 uv run python -m pytest tests/planner/strategy/test_price_reserve.py tests/planner/test_price_reserve_pipeline.py tests/api/test_price_forecast_api.py` plus the new accuracy tests
- [x] 5.2 Run `./scripts/lint.sh` and fix until it passes end to end
- [x] 5.3 Run `openspec validate price-reserve-forecast-accuracy --strict` and confirm it passes
