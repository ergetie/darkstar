## Why

The price reserve raises the end-of-horizon SoC target when forecast prices for the first unseen day look worse than the cheapest known hours. It trusts the D+1 `spot_p50` forecast blindly: on 2026-11-18 a user whose D+1 forecast bias was +0.38 SEK/kWh (d1_mae 0.52) saw the reserve add 7.7 kWh on a 0.24 SEK/kWh gap and flip on/off 5 times in 3 hours (GitHub #8). The decision is all-or-nothing against a fixed 0.10 SEK/kWh threshold (risk 3), so forecast noise larger than the threshold makes the target jump. The system already measures this accuracy (`/api/price-forecast/accuracy`) but the planner never reads it.

## What Changes

- Extract one shared accuracy computation (DB fetch plus pure maths: bias, MAE, de-biased MAE, sample days, status), parametrised by forecast horizon (`days_ahead`), used by both the `/api/price-forecast/accuracy` endpoint (D+1) and the planner, so both always report the same numbers. Endpoint output stays identical.
- De-bias every forecast-sourced slot the reserve uses, on the same basis: unseen-window slots AND known-window slots whose price comes from the D+1 forecast fallback (`price_source == "forecast"`, which exists before tomorrow's prices are published at 13:00). Real Nordpool slots are never adjusted. Each slot is corrected with the bias of its own horizon (its forecast row's `days_ahead`), falling back to D+1, then to no correction. Only the reserve's inputs are corrected; the solver's own price series is unchanged.
- Noise gate: the reserve activation threshold becomes `max(risk threshold, typical forecast error)`, where typical error is the MAE of the de-biased forecast (mean of `|error - bias|`) of the horizons actually used, converted to the import-price domain (VAT scaling).
- Carry `price_source` to the reserve: the planner price DataFrame drops it, so the pipeline derives the set of forecast-sourced known slots from `input_data["price_data"]` and hands it to `build_price_reserve_inputs` as a slot_start to `days_ahead` mapping (from the carried `forecast_days_ahead`, default 1).
- Fallback: fewer than 2 sample days, no rows or any fetch error gives bias 0 and error 0, i.e. exactly today's behaviour. Never raises into planning.
- Explainability: bias, typical error, effective threshold and a fallback flag are added to the price-reserve debug dict and the price-reserve strategy event.
- No new config keys, no per-user tuning, no schema change.

Non-goals: hysteresis or any persisted reserve state (needs state storage, separate change); changing the 90% coverage rule, sizing maths or risk table; applying the correction to EV deferral (follow-up, see design); the D+1 00:00 slot fix and benchmark relaxation (separate change `forecast-slot-benchmark-and-dead-config-fixes`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `s-index-price-awareness`: unseen-window prices are de-biased, the activation threshold is noise-gated, fallback and debug/event output cover the accuracy data.
- `price-forecast-accuracy-kpi`: the accuracy numbers are produced by a shared function that the planner also uses (endpoint contract unchanged).

## Impact

- Code: new `ml/price_accuracy.py` (shared function); `backend/api/routers/price_forecast.py` (use it); `planner/pipeline.py` (`build_price_reserve_inputs`, call site, event message); `planner/strategy/ev_deferral.py` (new `fetch_forecast_spot_with_horizon_sync` returning each slot's `days_ahead`; `fetch_forecast_spot_sync` unchanged); `frontend/src/lib/api.ts` (optional debug keys, types only); `planner/strategy/price_reserve.py` (`PriceReserveInputs`, `PriceReserveResult`, threshold gate); `planner/strategy/s_index.py` (`_price_reserve_debug`).
- Tests: `tests/planner/strategy/test_price_reserve.py`, `tests/planner/test_price_reserve_pipeline.py`, new shared-function tests, existing `tests/api/test_price_forecast_api.py` unchanged.
- Dependency: builds on `forecast-slot-benchmark-and-dead-config-fixes` (committed as 58945962, archived), which made the D+1 fallback pick the latest issue by date, set `forecast_days_ahead` on each fallback record and carries it (only on `price_source == "forecast"` slots) into `input_data["price_data"]` (horizon 1 when absent). `ml/price_accuracy.py` is new, so no other file overlap.
- No DB schema or config change; the only frontend change is optional debug-key types in `api.ts`.
