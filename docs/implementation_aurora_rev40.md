## Rev 40 — AURORA v0.1 ML Pipeline *(Status: ✅ Completed)*

* **Model**: Gemini
* **Summary**: Introduce the AURORA v0.1 machine-learning forecasting pipeline, reusing the existing learning engine and SQLite database without changing live planner behaviour by default.

### Plan

* **Goals**

  * Capture richer historical observations from Home Assistant into `slot_observations`.
  * Train LightGBM models for per-slot load and PV forecasts.
  * Run AURORA in shadow mode, storing forecasts alongside baseline in `slot_forecasts`.
  * Prepare a feature-flagged integration path for future planner use.

* **Scope**

  * Add `ml/data_activator.py` to backfill `slot_observations` using the existing `LearningEngine` and `input_sensors` from `config.yaml`.
  * Add `ml/train.py` to train LightGBM models using time-based features (hour, weekday, month, weekend, cyclic encodings) from `slot_observations`, saving models under `ml/models/`.
  * Add `ml/evaluate.py` to:
    * Generate baseline forecasts (`baseline_7_day_avg`) and AURORA forecasts (`aurora_v0.1`) for a historical evaluation window.
    * Persist both forecast sets into `slot_forecasts` with distinct `forecast_version` values.
    * Compute MAE for PV and load by joining `slot_observations` with `slot_forecasts`.
  * Extend `config.yaml` with `forecasting.active_forecast_version`, defaulting to `"baseline_7_day_avg"`.
  * Add `ml/api.py` and a thin helper in `inputs.py` to read `slot_forecasts` by time window and `forecast_version`, without yet altering planner behaviour.

### Implementation Summary

* `ml/data_activator.py`:
  * Uses `get_learning_engine()` and the shared SQLite DB at `learning.sqlite_path`.
  * Fetches Home Assistant history for sensors defined in `config.yaml:input_sensors`.
  * Converts cumulative readings into 15-minute slot deltas via `LearningEngine.etl_cumulative_to_slots`.
  * Persists the resulting per-slot observations via `LearningEngine.store_slot_observations`.

* `ml/train.py`:
  * Loads recent `slot_observations` within a configurable `--days-back` window.
  * Builds time-based features (`hour`, `day_of_week`, `month`, `is_weekend`, `hour_sin`, `hour_cos`).
  * Trains separate `LGBMRegressor` models for `load_kwh` and `pv_kwh`, with a configurable `--min-samples` guard.
  * Saves native LightGBM models to `ml/models/load_model.lgb` and `ml/models/pv_model.lgb`.

* `ml/evaluate.py`:
  * Loads trained models and generates AURORA forecasts over a historical evaluation window.
  * Computes a simple hourly baseline forecast (`baseline_7_day_avg`) from recent history.
  * Stores both baseline and AURORA forecasts into `slot_forecasts` with appropriate `forecast_version` values.
  * Computes and prints MAE for PV and load for each version, confirming AURORA outperforms the baseline in shadow mode.

* `ml/api.py` and `inputs.py` helper:
  * Provide a clean `get_forecast_slots(start, end, version)` API over `slot_forecasts`.
  * Add a helper in `inputs.py` that uses `forecasting.active_forecast_version` to select which forecast version to read, without yet changing the planner’s default behaviour.

* `config.yaml`:
  * Adds `forecasting.active_forecast_version: "baseline_7_day_avg"` to enable a config-only switch between baseline and AURORA once forward inference is wired.

### Verification

* Manual runs of:
  * `PYTHONPATH=. python ml/data_activator.py --days-back N` to populate `slot_observations`.
  * `PYTHONPATH=. python ml/train.py --days-back 90 --min-samples 500` to train and persist models.
  * `PYTHONPATH=. python ml/evaluate.py --days-back 7` to:
    * Store baseline and AURORA forecasts into `slot_forecasts`.
    * Report MAE for PV and load, showing AURORA improvements over the baseline.

