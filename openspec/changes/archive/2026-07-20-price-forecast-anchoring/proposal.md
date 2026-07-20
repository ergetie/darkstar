# Proposal: price-forecast-anchoring

## Why

Production price forecasts are generated with all three price-lag features (`price_lag_1d`, `price_lag_7d`, `price_lag_24h_avg`) permanently NaN: inference calls `build_price_features_batch` without a `db_session` (`ml/price_forecast.py:181-186`), so the model — trained to rely on those lags — predicts from calendar + weather only, with zero anchoring to the current price level. This is the verified root cause (investigated 2026-07-10) of the large actual-vs-forecast discontinuity at midnight (e.g. actual 0.16 SEK/kWh at 23:45 jumping to forecast 0.70 at 00:00). Additionally, training populates lags from historical actuals unconditionally (`ml/price_train.py:_add_price_lag_features`), including values that were unknowable at forecast issue time for D+2..D+7 rows — train-time leakage that makes the model over-trust lags it can never fully have in production.

## What Changes

- Inference (`ml/price_forecast.py`): open a DB session against the forecast DB and pass it to `build_price_features_batch`, so price lags are populated wherever the underlying observation exists. Knowability is enforced naturally: unobserved (future) slots have no `slot_observations` row and stay NaN.
- Training (`ml/price_train.py`): mask each lag feature to issue-time knowability — a lag value is kept only if its source timestamp precedes the row's `issue_timestamp`; otherwise NaN. Eliminates the leakage and makes training match what inference can actually see.
- Retrain the price model after both fixes and verify the D+1 actual-to-forecast boundary on production data (before/after comparison).
- Explicitly NOT included: any boundary blending/stitching post-processing. That is a fallback to be proposed separately only if a visible discontinuity remains after the root-cause fix (acceptance check in tasks).

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `price-forecasting`: the "Price forecast feature engineering" requirement changes — price lags SHALL be populated at inference from `slot_observations` (not left NaN by omission), and training SHALL respect issue-time knowability when materialising lag features.

## Impact

- **Code:** `ml/price_forecast.py` (`generate_price_forecasts`), `ml/price_train.py` (`_add_price_lag_features`); `ml/price_features.py` unchanged (already accepts `db_session`).
- **Model:** requires a retrain to take effect (existing scheduled training path); until retrained, populated lags feed a model trained on leaked lags — still strictly closer to training conditions than all-NaN.
- **Runtime:** inference gains ~3 DB point-queries per slot (~2,000 for a full 7-day run) on a scheduled background job — acceptable, not a hot path.
- **DB/schema:** none. **API:** none. **Frontend:** none.
- **Verification data source:** production `planner_learning.db` (`slot_observations`, `price_forecasts`) via `ssh darkstar`.
