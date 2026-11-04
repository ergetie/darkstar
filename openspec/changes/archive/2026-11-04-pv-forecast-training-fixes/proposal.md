# Proposal

## Why

Aurora's PV forecast has been systematically too high on cloudy days and misses by more than 30 % on many days (prod: 28 % of days, two other sites 18-20 %). Investigation (`debugging/pv-overforecast-2026-11/`) found that the PV model is trained without historical weather and on poorly cleaned data, that the Reflex confidence analyser can never fire, and that two persistence/parsing bugs silently discard data. Since commit be5e0803 (2026-10-17) raised `pv_residual_bound_fraction` to 1.0, live bias dropped from about +19 % to about +3 %; the remaining error is a training-data problem.

## What Changes

- Training fetches real historical weather (temperature, cloud cover, shortwave radiation) for the whole training window from the Open-Meteo historical-forecast API (archive API as fallback), resamples to 15 minutes and caches it. If the fetch fails, training continues without weather and logs a warning. Inference keeps using forecast weather.
- PV training data cleaning is replaced: shaded zero slots are kept, inverter dropouts, physically impossible spikes, night-time production and curtailed slots are dropped. The same cleaning feeds the Reflex confidence bias input.
- `slot_forecasts.pv_ml_residual_raw_kwh` stops being overwritten with NULL by the planner's re-upsert.
- The Open-Meteo PV baseline backfill honours tilt 0 and azimuth 0 instead of turning them into 30 and 180.
- Reflex confidence analyser switches from an absolute 0.5 kWh/slot bias threshold (never fires) to a relative bias over the 14-day window, firing at +/-10 %. Existing bounds and max daily change are kept.
- An informational, plain-language health notice appears when actual PV versus the Open-Meteo baseline on clear days is outside 0.55-1.30, pointing at shading, panel settings or a missing string. The user can acknowledge it; it stays hidden unless the ratio gets 0.10 worse or crosses to the other side. Acknowledgement is stored in the existing `data/onboarding_state.json` (no database change) and shown with existing banner UI.
- `pv_residual_bound_fraction` stays at 1.0 (no change).
- Removes the backlog item "[Forecasting] Systematic PV Over-Forecast" (promoted into this change).

Out of scope (tested, no gain): multiplicative/ratio target, sun elevation/azimuth model features, per-bin ratio table.

## Capabilities

### New Capabilities
- `pv-training-weather-history`: historical weather is supplied to PV/load model training, with graceful degradation.
- `pv-training-data-quality`: which PV slots are used for training and for the Reflex bias measurement.
- `pv-confidence-reflex`: Reflex adjusts `forecasting.pv_confidence_percent` from relative forecast bias.
- `pv-site-sanity-warning`: informational, acknowledgeable notice when recorded PV is implausible relative to the physics baseline.

### Modified Capabilities
- `ml-forecast-pipeline-integrity`: the stored raw ML residual survives planner re-upserts; baseline backfill honours tilt/azimuth 0.

## Impact

- `ml/train.py`, `ml/weather.py` (new historical fetch), new `backend/learning/pv_cleaning.py`, `backend/learning/store.py` (upsert COALESCE, `get_forecast_vs_actual`), `backend/core/forecasts.py`, `backend/learning/pv_openmeteo_backfill.py`, `backend/learning/reflex.py`, `backend/health.py`, new `backend/learning/pv_site_sanity.py`, `backend/core/onboarding_state.py`, `backend/api/routers/system.py`, `frontend/src/components/SystemAlert.tsx`, `frontend/src/lib/api.ts`.
- No schema change, no new dependency, no new config keys. Existing models keep working; the next training run produces models that use weather features. Open-Meteo gets one extra request per training run (cached).
