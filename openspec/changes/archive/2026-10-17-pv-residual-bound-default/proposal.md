## Why

The PV forecast is the Open-Meteo baseline plus an ML residual clamped to +/-`forecasting.pv_residual_bound_fraction` of the baseline (default 0.25). Open-Meteo has no shading or horizon model, so the baseline over-predicts, and the ML model already learns the correction through its hour and month features, but the 25% cap stops it. A read-only 90-day production replay (2026-07-18..2026-10-15, Open-Meteo historical-forecast archive) shows:

| Bound | Forecast vs actual | Per-slot MAE | Evening 15-19h ratio |
|-------|--------------------|--------------|----------------------|
| 0.25 | +20% | 0.092 kWh | 1.53 |
| 1.0 | +7.4% | 0.073 kWh (-21%) | 1.17 |

Better on 85 of 90 days. A downward-only bound gave no extra benefit, so the bound stays symmetric. Caveats: archive weather differs from live inputs, and the models are in-sample.

Two adjacent defects share the same `or`-fallback pattern: a configured 0 is silently replaced by the default (PV residual bound in `ml/forward.py`, panel tilt and azimuth in `ml/weather.py`).

## What Changes

- Default `forecasting.pv_residual_bound_fraction` raised from 0.25 to 1.0 in `config.default.yaml` and in the code fallback in `ml/forward.py`.
- `ml/forward.py`: a configured 0 is honoured (0 means "no ML nudge", baseline only); the default applies only when the key is missing or None. Negative or non-numeric values fall back to the default.
- One-time config migration `_migrate_pv_residual_bound` in `backend/config_migration.py`: a value of exactly 0.25 becomes 1.0; any other user value is kept; a missing key takes the template default. Idempotent.
- Persist the model's raw, uncapped PV p50 residual per slot so a future limit can be evaluated exactly. **DB schema change, approved by the user 2026-10-17**: new nullable column `slot_forecasts.pv_ml_residual_raw_kwh` plus an Alembic migration.
- `ml/weather.py`: panel `tilt` 0 (flat array) and `azimuth` 0 (north) are honoured; defaults (30, 180) apply only when missing or None.
- Reflex (`backend/learning/reflex.py`) does not tune this key (it only tunes `forecasting.pv_confidence_percent`, `load_safety_margin_percent` and similar), so no interaction.
- Settings UI: `frontend/src/pages/settings/types.ts` has no field for this key (only an optional type entry in `frontend/src/lib/api.ts`), so no UI change is needed beyond keeping the type; a task verifies this.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `ml-forecast-pipeline-integrity`: bounded-residual default and zero handling, raw residual persistence, panel orientation zero handling.
- `config-migration`: one-time migration of the old 0.25 default.

## Impact

- `config.default.yaml`, `ml/forward.py`, `ml/weather.py`, `backend/config_migration.py`
- `backend/learning/models.py`, `backend/learning/store.py`, new Alembic revision (down_revision `b7e2c4a9f1d3`) -- schema change approved 2026-10-17
- Tests under `tests/ml/` and `tests/`
- Aurora API/dashboard physics numbers change for arrays with tilt or azimuth 0
- Behaviour: PV forecasts move closer to actuals (less over-prediction, especially in the evening); users who never changed the default get the new default.
