## 1. Tests first

- [x] 1.1 Add a test for `_get_forecast_data_async` with a faked `OpenMeteoSolarForecast` (fixed-offset keys, prod-shaped series of ~7,830 entries starting ~66 days back) and a stubbed HA load profile, asserting per-slot `pv_forecast_kwh` equals the reference UTC-instant match
- [x] 1.2 Add a test that a slot with no matching series key gets 0.0 kWh
- [x] 1.3 Add a test asserting every array's `OpenMeteoSolarForecast` is constructed with `past_days=1`
- [x] 1.4 Run the new tests against current code: equality and zero-match pass, `past_days` test fails

## 2. Implementation

- [x] 2.1 Replace the per-slot linear scan in `backend/core/forecasts.py` `_get_forecast_data_async` with `solar_data_dict.get(rounded_time, 0.0)`
- [x] 2.2 Pass `past_days=1` to `OpenMeteoSolarForecast` in the same function
- [x] 2.3 Verify `daily_pv_forecast` consumers (`planner/strategy/s_index.py`) only read today onward

## 3. Verification

- [x] 3.1 Run the new tests and `tests/ml/test_forecast_aggregation.py`
- [x] 3.2 Rerun the local prod-shaped benchmark and confirm mapping drops from ~4 s to milliseconds with identical output
- [x] 3.3 Run `./scripts/lint.sh`
