## Why

The battery planner only sees published Nordpool prices (today, plus tomorrow after ~13:00), so it never stores cheap energy for the first day it cannot see. The existing price-driven floor addon tries to do this but compares daily averages against a 14-day mean; a leakage-free replay on production data (summer and winter 2025-26) shows it is worth ~0 SEK/month and loses money on ~40% of days. A rule that compares the *cheapest charging hours* of the first unseen day with the cheapest hours still available in the known window was worth ~50-70 SEK/month (hindsight ceiling ~90-120). Separately, the price forecast is issued only once a day at 06:00, before tomorrow's prices are published, so at the afternoon decision point it ignores the strongest signal available; re-issuing it after publication cut daily forecast error by ~6%.

## What Changes

- **BREAKING (behaviour)**: Remove the Layer 2 "price floor addon" (proximity-weighted daily-average spread × `RISK_PRICE_KW_FRACTION`) and its inputs fetch (`calculate_price_floor_addon`, `fetch_price_floor_inputs`, `_fetch_price_floor_inputs_sync`, related constants and tests).
- Add a **price reserve** for the first unseen day: at every full planner run, compare the forecast import cost of that day's cheapest charging hours with the cheapest charging hours left in the known window. When storing now beats buying later by more than a risk-dependent threshold, raise the end-of-horizon SoC target so the solver charges in the cheapest known hours. Size the reserve from that day's forecast net load in the hours where it pays off, limited by the user's own battery power, efficiencies, wear cost, SoC limits, fee model (flat or time-of-use) and what can physically be charged in the known window.
- The reserve never double-counts the existing deficit-based safety floor (Layer 1): the final target is the larger of the two, not their sum.
- Issue a **second price forecast per day, as soon as tomorrow's prices are published**, for D+2..D+7, using the published D+1 prices as lag inputs. Throttled, idempotent across restarts, skipped if prices are never published that day.
- Persist, per forecast row, the end of the published-price horizon at issue time, so training masks lags exactly as they were knowable at inference. Rows from before this change keep today's masking rule.
- Replace the per-run "Price signal" strategy events with a deduplicated price-reserve event (logged only when the reserve materially changes).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `s-index-price-awareness`: all requirements of the daily-average floor addon are removed and replaced by the first-unseen-day price reserve (decision rule, sizing, per-user limits, combination with the safety floor, fallbacks, debug and events).
- `price-forecasting`: lag features may use published prices; training masks lags by the stored published-price horizon; a second, publication-triggered forecast run for D+2..D+7; persistence stores the published-price horizon.

## Impact

- **Code**: `planner/strategy/s_index.py` (remove addon, add reserve), `planner/pipeline.py` (inputs, integration, remove old fetch), `planner/solver/adapter.py` (extract shared battery power-limit resolver), `ml/price_forecast.py`, `ml/price_features.py`, `ml/price_train.py`, `backend/services/scheduler_service.py`, `backend/learning/models.py`.
- **Database**: one additive, nullable column on `price_forecasts` (`known_prices_until`) via a new Alembic migration. No data rewrite; legacy rows stay valid.
- **Config**: no new keys. Behaviour adapts through existing settings: `s_index.risk_appetite`, battery capacity/SoC limits/efficiencies/power limits (A or W control unit), `battery_economics.battery_cycle_cost_kwh`, `pricing` (flat or time-of-use fees), `nordpool.price_area`, `price_forecast.enabled`.
- **Tests**: `tests/planner/strategy/test_s_index_price_awareness.py` and `tests/planner/test_price_floor_known_prices.py` are replaced; new tests for reserve sizing, forecast lag knowability, scheduler trigger, migration.
- **External calls**: one extra Open-Meteo weather fetch per day (afternoon forecast run); Nordpool publication checks are throttled.
- **Users**: works in all price areas (SE1-SE4 and others supported by the forecast) because every input is the user's own area, fees and hardware. With `price_forecast.enabled: false` behaviour equals today's Layer 1 floor only.
