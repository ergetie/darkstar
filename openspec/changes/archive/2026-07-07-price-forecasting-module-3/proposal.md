## Why

The S-Index currently determines battery safety floors using only PV/load deficit ratios, temperature forecasts, and weather volatility. It has no awareness of electricity prices. This means the system cannot anticipate cheap recharge windows days ahead (drain battery today, recharge cheaply tomorrow) or stockpile energy before an expensive period. Module 1 (price-forecasting-core) delivers 7-day spot price forecasts — this change makes the S-Index consume them.

## What Changes

- Add a **price floor addon** to the `calculate_safety_floor()` function that raises the base safety floor when expensive periods are forecast in the upcoming 7 days. The signal is **time-proximity weighted** (exponential decay, half-life 2 days): an expensive day tomorrow counts fully, one at D+7 barely registers, and the floor ramps up as an expensive day approaches — matching the battery's realistic 1–2 day bridging horizon.
- Apply the addon **after** the existing `max_safety_buffer_pct` cap (Layer 1), so it is not silently discarded on days when the cap is already binding.
- Negative addons (cheap period ahead) **never undercut the deficit-based safety floor** — price optimization is additive only; physical safety is preserved as a hard lower bound. Cheap-period exploitation is left to Kepler's natural slot-level optimization.
- Scale the addon by **risk appetite** via an internal `RISK_PRICE_KW_FRACTION` table (Safety = 0.15, Gambler = 0.02). No user-facing config knob — risk appetite is the single lever.
- All price-based adjustments are **gated behind `price_forecast.enabled`** and gracefully degrade to current behavior when disabled or when no forecast data is available.
- Emit detailed debug data for price-based adjustments in the existing `s_index_debug` output for observability.
- Log price-trend strategy decisions to the existing `strategy_log` table via `append_strategy_event()` only when the addon meaningfully raises the floor (≥ 0.5 kWh).

## Capabilities

### New Capabilities
- `s-index-price-awareness`: Integrating 7-day price forecast trends into the S-Index safety floor and load inflation calculations.

### Modified Capabilities
None. Price data is fetched by a new, self-contained pipeline helper (`fetch_price_floor_inputs()`, per design Decision 5) — the existing probabilistic forecast retrieval and calculation (`s-index-probabilistic`) are untouched. The pipeline-integration requirement lives in the `s-index-price-awareness` spec.

## Impact

- **Code**: `planner/strategy/s_index.py` (primary), `planner/pipeline.py` (wire price forecast data into S-Index calls), `backend/strategy/engine.py` (optional strategy rules for price events).
- **Config**: New optional fields under `s_index` section in `config.yaml` / `config.default.yaml`.
- **Dependencies**: Requires Module 1 (price-forecasting-core) to be implemented — specifically the `price_forecasts` DB table and `GET /api/price-forecast` endpoint.
- **Tests**: New unit tests for price-aware S-Index behavior. Updates to existing S-Index tests to verify backward compatibility when price data is absent.
- **No breaking changes**: All modifications are additive and gated. Existing behavior is preserved when `price_forecast.enabled` is false or price data is unavailable.
