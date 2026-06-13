## Why

The planner's Temporal Safety Floor is supposed to "look beyond the price horizon" using extended load/PV forecast data for a 24h window (see `planner` spec, Requirement: *End-of-Horizon SoC Target acts as a Minimum Floor*). In practice it **never** does: on every plan it logs `Temporal Safety Floor: Extended forecast data unavailable or insufficient, using available horizon only` and falls back. The forecast data exists in the DB (slot_forecasts extends ~7 days ahead), but the planner only loads slot-level forecasts covering the price horizon (~2 days), so the look-ahead window beyond the price horizon is always empty. The safety floor's overnight/next-day deficit reservation is therefore inert — harmless in summer (deficit ≈ 0) but under-provisioning battery before cold, dark winter stretches.

## What Changes

- Supply slot-level extended load/PV forecast data (covering at least 24h beyond the price horizon) to the safety-floor calculation, so `calculate_safety_floor()` can compute the temporal deficit over the intended look-ahead window instead of always hitting the fallback.
- The extended forecast slots are already fetched in `_get_forecast_data_aurora()` (`backend/core/forecasts.py`) but are currently consumed only to build daily aggregates. Pass them through to the planner pipeline as slot-level data (e.g. an `extended_forecast_data` key) without altering the main Kepler planning horizon, which remains intentionally bounded by the price horizon.
- Build the safety-floor's `full_forecast_df` from this extended slot data rather than from the price-horizon-only `forecast_data`.
- Preserve the existing fallback-and-warn behavior for the case where extended data genuinely does not exist (e.g. early in deployment or a forecast outage).
- No change to Kepler optimization scope, price loading, or the schedule horizon.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `planner`: Clarify the *Safety Floor* requirement so that the forecast data supplied to the safety-floor calculation MUST include slot-level forecasts extending at least 24h beyond the price horizon when such data exists, and the "extended forecast data unavailable" fallback applies only when that data is genuinely absent (not merely unloaded). Add scenarios pinning the data-provisioning contract.

## Impact

- **Code:**
  - `backend/core/forecasts.py` — `_get_forecast_data_aurora()` (and sibling forecast-data builders): expose extended slot-level forecasts beyond the price horizon, not just daily aggregates.
  - `planner/pipeline.py` — build the safety-floor `full_forecast_df` from the extended forecast slots.
  - `planner/strategy/s_index.py` — `calculate_safety_floor()`: consume the extended slot-level data; fallback path unchanged.
- **Behavior:** In winter / short-price-horizon conditions the safety floor will now reserve battery for the night/day beyond the price horizon as originally specified. Summer behavior is unchanged (temporal deficit remains ≈ 0). The recurring per-plan warning stops appearing on healthy systems.
- **Data/DB:** No schema change. Uses existing `slot_forecasts` rows already persisted ~7 days ahead.
- **No breaking changes.**
