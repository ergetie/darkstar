## Why

Every planner run spends ~34-38 s of its ~50 s wall time mapping the live Open-Meteo PV forecast onto slots, while the MILP solve itself takes <1 s. Measured on prod 2026-09-27: the mapping loop in `_get_forecast_data_async` took 33.5 s on real data; a direct lookup produced identical output in 7 ms. The cause is a linear scan per slot over a solar series that carries ~66 days of unused history, because the live fetch never sets `past_days` and inherits the library default of 92.

## What Changes

- Map Open-Meteo PV power to slots with a direct timestamp lookup instead of scanning the whole series for every slot. Output is unchanged.
- Request only the history the live forecast path can use (`past_days=1`) instead of the library default (92 days), for every configured solar array.
- No behaviour, API, config, or schema changes. The ML backfill path (`pv_openmeteo_backfill.py`) and the dashboard hindcast path (`ml/weather.py`) are untouched.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `open-meteo-pv-forecast`: adds requirements that live slot mapping stays efficient regardless of series length and that the live PV fetch requests at most one past day.

## Impact

- `backend/core/forecasts.py` (`_get_forecast_data_async`): slot mapping and `OpenMeteoSolarForecast` construction.
- Callers that benefit: Aurora forward inference (`ml/forward.py` Open-Meteo baseline), non-Aurora forecast path, and Aurora path with PV disabled.
- Less Open-Meteo payload per run (per array), shorter planner runs on all installs.
- Tests: `tests/ml/test_forecast_aggregation.py` or a new focused test.
