## Why

On 2026-09-24 the multi-day EV quota gave Thursday 11 kWh (charging ~23:00–24:00 at ~2.0 SEK spot) for a goal due Monday, even though the weekend was forecast far cheaper. Root cause: the per-day prices fed to the quota split come only from the ML `price_forecasts` table, even for slots whose real Nordpool price is already published. Today's slots were last forecast the day before (~0.2 SEK) while the real price was ~2.0 SEK, so today looked like the cheapest day by far. The same forecast-only read makes the 7-day outlook show forecast values for D+1 after real prices are known.

## What Changes

- Introduce a single "best known spot price per slot" source: published Nordpool spot wins for every slot where it exists; the ML forecast (`spot_p50`, latest issue per slot) is used only for slots without a published price.
- Nordpool entries that are themselves the D+1 forecast fallback (pre-13:00) SHALL NOT count as known prices.
- `fetch_price_floor_inputs` (planner) uses this source for its per-day averages. Today keeps counting only remaining slots (`slot_start >= now`). This fixes the EV multi-day quota split and also the battery safety-floor price addon, which consumes the same function.
- The daily price outlook (`/api/price-forecast/outlook`) uses the same source, so days with published prices show real spot aggregates.
- Log which source (known vs forecast slot counts) each day's average came from.

## Capabilities

### New Capabilities
- `known-price-precedence`: a shared per-slot spot price resolver where published Nordpool prices always take precedence over forecasts.

### Modified Capabilities
- `multi-day-deferral-controller`: daily prices supplied to the planner SHALL come from known prices where published, forecast only otherwise.
- `price-outlook-api`: daily summaries SHALL use published spot prices for slots where they exist.

## Impact

- `backend/core/prices.py` (mark fallback vs Nordpool entries; new resolver)
- `planner/pipeline.py` `_fetch_price_floor_inputs_sync` / `fetch_price_floor_inputs` (EV quota + safety floor callers)
- `backend/core/price_outlook.py` `get_daily_outlook`, plus its callers `backend/api/routers/price_forecast.py` and `backend/api/routers/analyst.py` (Aurora advisor price alerts)
- Tests under `tests/planner/`, `tests/backend/`
- No schema change, no new dependency, no API shape change.
