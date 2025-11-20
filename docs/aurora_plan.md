# AURORA: Implementation Plan

**AURORA**: **A**daptive **U**sage & **R**enewables **O**ptimization & **R**esponse **A**nalyzer

This document outlines the plan for developing and integrating AURORA, a machine learning-based forecasting engine, into the Darkstar Energy Manager. It serves as a living working plan, updated with each step and sub-step of the implementation.

---

## AURORA: An Overview

### Goal & Purpose

The primary goal of AURORA is to replace the current simple-average forecasting method with a sophisticated, self-improving machine learning engine. This will enable the Darkstar planner to create significantly more accurate and efficient energy schedules by proactively predicting the unique energy "rhythm" of the home, rather than just reacting to past usage.

By understanding the drivers behind energy consumption (like weather, time of day, and user habits), AURORA will provide the planner with a high-fidelity forecast of future energy load and solar production, leading to better optimization and greater cost savings.

### Architecture & Data Flow

AURORA is designed as a distinct module that integrates seamlessly with the existing Darkstar components **while reusing the current learning engine and database**. The implementation follows a safe, phased approach:

1.  **Data Collection (via LearningEngine):** A robust data pipeline collects and stores historical data from Home Assistant (energy usage, user states) and a weather API (temperature, cloud cover) using the existing `LearningEngine` in `learning.py`, into the single SQLite database at `learning.sqlite_path` (default `data/planner_learning.db`). AURORA does **not** introduce a second DB or schema.
2.  **Offline Training:** Using the collected data, machine learning models will be trained to predict load and PV production. This step is performed offline and has no impact on the live system.
3.  **Shadow Mode Evaluation (forecast_version):** The trained models are run in a "shadow mode," where their predictions are written into the existing `slot_forecasts` table with a distinct `forecast_version` (e.g. `aurora_v1.0`) and then compared against the baseline forecasts and actual results from `slot_observations`. This provides objective proof of performance before integration.
4.  **Live Integration (feature-flagged):** Once proven, AURORA will be integrated into the planner's `inputs.py` module via a small ML API (`ml/api.py`), controlled by a feature flag in `config.yaml` (e.g. `forecasting.active_forecast_version`) for safety and easy rollback. Until that flag is switched, the live system continues to use the existing baseline forecasts.

### Folder Structure

To ensure a clean separation of concerns, all AURORA-related code will reside in a new top-level `/ml` directory, acting as a client of the existing learning engine:

```
/ml/
├── data_activator.py  # Script to call LearningEngine and populate training data
├── train.py           # Script to train the AURORA models
├── evaluate.py        # Script to run shadow-mode evaluation using slot_forecasts
├── api.py             # Thin API: e.g. get_forecast_slots(start, end, version)
└── models/            # Directory to store the trained model files
```

### Machine Learning Model

The chosen model for AURORA is **LightGBM** (Light Gradient Boosting Machine). It is a state-of-the-art algorithm that is ideal for this project due to its:
*   **High Accuracy:** Excellent performance on tabular data like ours.
*   **Speed & Efficiency:** Fast training times and low memory usage, making it perfectly suited for running on devices like a Raspberry Pi.

---

## Revision Template

*   **Rev [X] — [YYYY-MM-DD]**: [Title] *(Status: ✅ Completed / 🔄 In Progress / 📋 Planned)*

    *   **Model**: [Agent/Model used]
    *   **Summary**: [One-line overview]
    *   **Started**: [Timestamp]
    *   **Last Updated**: [Timestamp]

    **Plan**

    *   **Goals**:
    *   **Scope**:
    *   **Dependencies**:
    *   **Acceptance Criteria**:

    **Sub-steps**

    *   [1] [Short label for sub-step 1]
    *   [2] [Short label for sub-step 2]
    *   [3] [Short label for sub-step 3]
    *   [4] [Short label for sub-step 4]

    **Implementation**

    *   **Completed**:
    *   **In Progress**:
    *   **Blocked**:
    *   **Next Steps**:
    *   **Technical Decisions**:
    *   **Files Modified**:
    *   **Configuration**:

    **Verification**

    *   **Tests Status**:
    *   **Known Issues**:
    *   **Rollback Plan**:

    **Backlog items**
    * Sectioned list
---

## Phase 1: Data Pipeline Activation & Model Training

**Goal:** Activate the existing data collection mechanisms and train the first models using historical data.

### Rev 1 — 2025-11-16: Initial Setup & Folder Structure *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Create the base directory and file structure for AURORA development.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**: Establish the `/ml` directory and its subdirectories.
    *   **Scope**: Create `/ml`, `/ml/models`, and placeholder files.
    *   **Dependencies**: None.
    *   **Acceptance Criteria**: The specified directory structure exists.

### Rev 2 — 2025-11-16: Update `config.yaml` with `input_sensors` *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Add a dedicated `input_sensors` section to `config.yaml` to map canonical sensor roles to user-specific Home Assistant entity IDs, to be used first by AURORA and later by the rest of Darkstar.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**: Create a flexible and user-configurable mapping for all sensors required by AURORA, and eventually by the planner and learning engine.
    *   **Scope**: Add the `input_sensors` section to `config.yaml`. `secrets.yaml` will only be used for the HA URL and token. Initially, only AURORA reads from `input_sensors`; a later Darkstar refactor will migrate `learning.py`, `inputs.py`, and related components to use this same map.
    *   **Dependencies**: None for AURORA sandbox use; full app migration depends on the Darkstar config refactor backlog item.
    *   **Acceptance Criteria**: `config.yaml` contains the `input_sensors` section with real entity IDs for the running system, and AURORA code can resolve canonical sensor names from it without affecting the live planner.
    *   **Configuration**: Add the following to `config.yaml`:
        ```yaml
        input_sensors:
          # Map canonical names to your specific Home Assistant entity IDs
          total_load_consumption: "sensor.your_total_load_consumption_sensor"
          total_pv_production: "sensor.your_total_pv_production_sensor"
          total_grid_import: "sensor.your_total_grid_import_sensor"
          total_grid_export: "sensor.your_total_grid_export_sensor"
          total_battery_charge: "sensor.your_total_battery_charge_sensor"
          total_battery_discharge: "sensor.your_total_battery_discharge_sensor"
          battery_soc: "sensor.inverter_battery"
          water_heater_consumption: "sensor.vvb_energy_daily"
          vacation_mode: "input_boolean.vacation_mode"
        ```
        *(Note: User will replace placeholder sensor names with actual entity IDs.)*

### Rev 3 — 2025-11-16: Implement `ml/data_activator.py` *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Create a script to activate the existing `etl_cumulative_to_slots` logic in `learning.py`, populating the `slot_observations` table with rich historical data based on the new `input_sensors` config.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Leverage the existing ETL functionality in `learning.py` to populate the database.
        *   Backfill the `slot_observations` table with historical data (June-Nov 2025).
        *   Ensure the script can be run periodically to append new data.
    *   **Scope**:
        *   Create a new script `ml/data_activator.py`.
        *   This script will import `LearningEngine` from `learning.py`.
        *   It will read the sensor mappings from the `input_sensors` section of `config.yaml`.
        *   It will fetch historical data for all mapped sensors from Home Assistant.
        *   It will call the existing `etl_cumulative_to_slots` method to process the data.
        *   It will then call `store_slot_observations` to save the processed data to the `planner_learning.db`.
    *   **Dependencies**: `config.yaml` updated with sensor mappings (Rev 2).
    *   **Acceptance Criteria**:
        *   The `slot_observations` table in `data/planner_learning.db` is populated with historical data, including non-zero values for `load_kwh`, `pv_kwh`, etc.
        *   Running the script appends new data points correctly.

### Rev 4 — 2025-11-16: Implement `ml/train.py` *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Create a Python script to train LightGBM models for Load and PV forecasting using the data in `slot_observations`.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Successfully train and save LightGBM models for Load and PV.
    *   **Scope**:
        *   Load data from the `slot_observations` table in `data/planner_learning.db`.
        *   Fetch corresponding weather data from Open-Meteo.
        *   Perform feature engineering (hour, day_of_week, etc.).
        *   Train a LightGBM Regressor for `load_kwh`.
        *   Train a LightGBM Regressor for `pv_kwh`.
        *   Save both trained models to `/ml/models/load_model.lgb` and `/ml/models/pv_model.lgb`.
    *   **Dependencies**: `slot_observations` table is populated (Rev 3).
    *   **Acceptance Criteria**:
        *   `load_model.lgb` and `pv_model.lgb` files exist in `/ml/models/`.

---

## Phase 2: Shadow Mode & Evaluation

**Goal:** Prove that the AURORA models are more accurate than the existing forecasting method before integrating them.

### Rev 5 — 2025-11-16: Implement `ml/evaluate.py` *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Create a Python script to compare AURORA's predictions against the old forecasting model and actual historical data using the shared `slot_forecasts` table and `forecast_version`.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Objectively measure the performance of AURORA models using a shared database and `forecast_version`.
    *   **Scope**:
        *   Load trained AURORA models from `/ml/models/`.
        *   Fetch actual historical data for a specified period (e.g., last 7 days) from `slot_observations`.
        *   Generate predictions using AURORA for that period and write them into `slot_forecasts` with a distinct `forecast_version` (e.g. `aurora_v1.0`).
        *   Ensure baseline forecasts are also present in `slot_forecasts` under a separate `forecast_version` (e.g. `baseline_7_day_avg`) if not already generated.
        *   Calculate and report Mean Absolute Error (MAE) and related metrics for both `forecast_version` values by joining against `slot_observations`.
    *   **Dependencies**: Trained AURORA models (Rev 4), populated `slot_observations` table.
    *   **Acceptance Criteria**:
        *   A clear performance report is generated, comparing AURORA and baseline forecasts using the single SQLite DB and the `forecast_version` field.

---

## Phase 3: Integration & Go-Live

**Goal:** Safely integrate the proven AURORA models into the live planner, with a safety switch to revert if needed.

### Rev 6 — 2025-11-16: Update `config.yaml` with AURORA Feature Flag *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Add a feature flag to `config.yaml` to enable/disable AURORA forecasting.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**: Provide a safe mechanism to switch between AURORA and the old forecasting method.
    *   **Scope**: Add a `forecasting` section with a `active_forecast_version` field to `config.yaml` to select which `forecast_version` from `slot_forecasts` drives the planner (e.g. `"baseline_7_day_avg"` vs `"aurora_v1.0"`).
    *   **Configuration**:
        ```yaml
        forecasting:
          active_forecast_version: "baseline_7_day_avg"  # default to baseline for safety
        ```

### Rev 7 — 2025-11-16: Modify `inputs.py` for AURORA Integration *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Integrate AURORA models into `inputs.py` to provide forecasts to the planner, controlled by the feature flag.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Enable the planner to receive forecasts from AURORA.
    *   **Scope**:
        *   Introduce a thin ML API in `ml/api.py` (e.g. `get_forecast_slots(start, end, version)`).
        *   Modify the `get_forecast_data` function in `inputs.py` to read from the `slot_forecasts` table via `ml/api.py`, selecting rows based on `forecasting.active_forecast_version`.
        *   Keep the old 7-day average logic available as a baseline `forecast_version` until AURORA is fully validated.
    *   **Dependencies**: Trained AURORA models (Rev 4), `config.yaml` feature flag (Rev 6).
    *   **Acceptance Criteria**:
        *   When `forecasting.use_aura` is `true`, the planner receives forecasts generated by AURORA.

### Rev 8 — 2025-11-16: Finalization and Cleanup *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Document AURORA v0.1, confirm sandboxed behaviour, and capture a backlog for future revisions.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Clearly document the AURORA v0.1 pipeline and its sandboxed status.
        *   Capture follow‑up ideas (v0.2 and beyond) in a dedicated backlog.
    *   **Scope**:
        *   Update `README.md` with a short description of AURORA v0.1.
        *   Keep AURORA v0.1 strictly shadow‑mode only (no planner integration yet).
        *   Add a backlog section describing weather, context features, UI toggles, and other future work.
    *   **Dependencies**: AURORA v0.1 pipeline (Revs 3–7) completed and validated.
    *   **Acceptance Criteria**:
        *   `README.md` briefly describes AURORA as an experimental, sandboxed forecasting pipeline.
        *   This document (`aurora_plan.md`) contains a clear backlog for future AURORA work.

---

### Rev 9 — 2025-11-17: AURORA v0.2 (Enhanced Shadow Mode) *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Upgrade AURORA while keeping it sandboxed by adding weather and behavioural features, and introduce a Forecasting tab in the UI for deeper evaluation, without yet letting AURORA drive the live planner.
*   **Started**: 2025-11-17
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Improve forecast fidelity with weather and context features.
        *   Provide rich observability via a Forecasting tab and metrics.
        *   Keep AURORA strictly in shadow mode (planner still uses baseline forecasts).

    *   **Scope**:
        *   **Weather & features**:
            *   Extend the training and evaluation pipeline to include per‑slot temperature:
                *   Fetch or join Open‑Meteo (or equivalent) data and populate `temp_c` in `slot_forecasts`.
                *   Add temperature (and potentially simple derived features) as model inputs in `ml/train.py`.
            *   Promote `vacation_mode` (and potentially other HA booleans) to proper input features:
                *   Ensure historic on/off state is available for the training window.
                *   Feed `vacation_mode` (and weekend/holiday flags) into the LightGBM models.
        *   **Evaluation & metrics**:
            *   Extend `ml/evaluate.py` to optionally report MAE segmented by:
                *   Weather regimes (e.g. cold vs mild days).
                *   Occupancy state (`vacation_mode` on/off).
            *   Keep all evaluation writes confined to `slot_forecasts` (no planner behaviour change).
        *   **UI / Forecasting tab**:
            *   Add a Forecasting tab in the React UI that:
                *   Shows the currently active `forecast_version` from config.
                *   Visualises baseline vs AURORA vs actuals for selected days.
                *   Displays recent MAE and coverage metrics for both versions.
            *   Optionally introduce an AURORA toggle in Settings that:
                *   Controls which `forecast_version` the Forecasting tab highlights.
                *   May write `forecasting.active_forecast_version` in config,
                  but does **not** yet change which forecasts the planner uses.

    **Sub-steps**

    *   [1] (Done) Integrate per-slot temperature (`temp_c`) into training/evaluation and populate it in `slot_forecasts`.
    *   [2] (Done) Add `vacation_mode` and `alarm_armed_flag` (and related boolean/context flags) as model input features.
    *   [3] (Done) Extend `ml/evaluate.py` with segmented MAE reporting (by weather regime and occupancy).
    *   [4] (Done) Implement a Forecasting tab (and view-only AURORA toggle) in the UI that surfaces baseline vs AURORA vs actuals and MAE metrics, without changing planner behaviour.

    *   **Dependencies**: Revs 3–8 completed (v0.1 pipeline, evaluation, ML API, config flag, and docs).

    *   **Acceptance Criteria**:
        *   Weather and `vacation_mode` (or equivalent) are available as features in training and evaluation.
        *   `slot_forecasts.temp_c` is non‑null for new forecasts generated during evaluation.
        *   `ml/evaluate.py` can produce segmented MAE reports (e.g. by occupancy or temperature band).
        *   A Forecasting tab exists in the UI, showing baseline vs AURORA vs actuals and MAE metrics.
        *   The live planner still runs on the baseline path by default; AURORA remains sandboxed.

---

## Phase 4: AURORA v0.3 — Forward Inference & Planner Wiring (Still Controlled)

**Goal:** Teach AURORA to generate forward-looking forecasts for the planner horizon and add a config/UX path to let the planner *optionally* consume them, while keeping rollback trivial and avoiding a “hard cutover” until we are happy with real‑world results.

### Rev 10 — 2025-11-17: Forward AURORA Inference *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Generate future AURORA forecasts for the planner horizon and store them in `slot_forecasts` under `aurora`.
*   **Started**: 2025-11-17
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Produce forward AURORA forecasts (PV + load) for each 15-min slot in the planner horizon.
        *   Use the same features as training (time, temp, context flags) with forecasted weather.

    *   **Scope**:
        *   Add a forward-inference helper (e.g. `ml/forward.py` or a function in `ml/api.py`) that:
            *   Uses trained models and Open-Meteo **forecast** temperatures (reusing planner’s `_fetch_temperature_forecast` logic or a shared helper).
            *   Builds a feature frame for all future slots in the chosen horizon (e.g. next 48–96 slots).
            *   Writes per-slot forecasts into `slot_forecasts` as `forecast_version='aurora'`.
        *   Provide a CLI/script wrapper so forward inference can be run manually or from a cron/systemd job.
    *   **Dependencies**: Revs 3–9 (v0.1/v0.2 pipeline, models, ML API).

    **Sub-steps**

    *   [1] (Done) Implement `ml/forward.py` to generate forward AURORA forecasts for the planner horizon and store them as `aurora` in `slot_forecasts`.
    *   [2] (Done) Update `ml/weather.get_temperature_series` to use Open-Meteo archive for historical windows and forecast API for future windows, so `temp_c` is available for forward slots when possible.
    *   [3] (Done) Add a short CLI/ops note (and optional cron/systemd example) documenting how and when to run forward inference in real deployments.

    **Implementation**

    *   **Completed**:
        *   Forward inference implemented in `ml/forward.py` with a simple CLI:
            *   `PYTHONPATH=. python ml/forward.py`
        *   Running the script generates 15‑minute AURORA forecasts for the next 48 hours and stores them in `slot_forecasts` with `forecast_version='aurora'`.
        *   Forward inference is safe to run repeatedly; existing future rows for `aurora` are overwritten for the same `slot_start`.
        *   Example cron entry (run every hour at minute 5):
            *   `5 * * * * cd /opt/darkstar && PYTHONPATH=. /opt/darkstar/venv/bin/python ml/forward.py >> /opt/darkstar/logs/aurora_forward.log 2>&1`

    *   **Acceptance Criteria**:
        *   Invoking the forward-inference entrypoint populates `slot_forecasts` with `aurora` rows for the planner horizon.
        *   Forecast rows include `slot_start`, `pv_forecast_kwh`, `load_forecast_kwh`, and `temp_c`.
        *   No changes to planner behaviour yet; the planner still uses the existing baseline forecast path.

### Rev 11 — 2025-11-17: Planner Consumption via Feature Flag *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Allow the planner to optionally consume AURORA forecasts instead of the baseline, controlled purely by `forecasting.active_forecast_version`.
*   **Started**: 2025-11-17
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Let the planner use either baseline or AURORA forecasts with a simple config switch.
        *   Preserve an instant rollback path by flipping `active_forecast_version`.

    *   **Scope**:
        *   Update `inputs.get_forecast_data` (or an adjacent helper) to:
            *   When `forecasting.active_forecast_version` is `"baseline_7_day_avg"`:
                *   Use the current baseline forecast path (status quo).
            *   When `forecasting.active_forecast_version` is `"aurora"`:
                *   Fetch forecasts from the learning DB via `ml.api.get_forecast_slots(...)` for the planner horizon.
                *   Fall back to baseline logic if AURORA data is missing, incomplete, or stale.
        *   Ensure timezone, slot alignment, and shapes match the planner’s expectations.
    *   **Dependencies**: Rev 10 (forward AURORA forecasts available in `slot_forecasts`).

    **Sub-steps**

    *   [1] (Done) Add a helper in `inputs.py` that can build planner-ready PV/load arrays from `slot_forecasts` for a given `forecast_version` and horizon.
    *   [2] (Done) Wire `get_forecast_data` to branch on `forecasting.active_forecast_version` and pull from AURORA via `ml.api.get_forecast_slots(...)` when set to `"aurora"`, with automatic fallback to baseline.
    *   [3] (Done) Add defensive logging/metrics when AURORA data is missing or stale so operators can see when the planner falls back to baseline.

    **Implementation**

    *   **Completed**:
        *   `inputs.build_db_forecast_for_slots` builds planner-style `{pv_forecast_kwh, load_forecast_kwh}` arrays from `slot_forecasts` for the active `forecast_version`, or returns an empty list when no DB forecasts exist for the horizon.
        *   `get_forecast_data` now:
            *   Uses AURORA forecasts from the learning DB when `forecasting.active_forecast_version == "aurora"` and any DB forecasts exist for the current horizon.
            *   Falls back to the existing baseline PV/load pipeline when no DB forecasts exist for the horizon, logging a warning if AURORA data is missing.
        *   Logging:
            *   Prints an info line when AURORA forecasts are used.
            *   Prints a warning when falling back to baseline because AURORA forecasts are missing or all-zero for the horizon.

    *   **Acceptance Criteria**:
        *   With `active_forecast_version="baseline_7_day_avg"` the planner behaves exactly as before.
        *   With `active_forecast_version="aurora"` and fresh AURORA forecasts present, the planner uses AURORA forecasts for PV/load while preserving existing safety margins.
        *   If AURORA data is missing or stale, the planner automatically falls back to baseline and logs a warning.

### Rev 12 — 2025-11-17: Settings Toggle for Active Forecast Version *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Expose the active forecast version as a controlled toggle in the Settings UI, so operators can switch between baseline and AURORA without touching YAML.
*   **Started**: 2025-11-17
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Make it easy and safe to switch between baseline and AURORA in production.
        *   Keep AURORA v0.3 clearly marked as experimental in the UI.

    *   **Scope**:
        *   Backend:
            *   Extend `/api/config` and `/api/config/save` (if needed) so `forecasting.active_forecast_version` can be read/written via the API.
        *   Frontend (Settings tab):
            *   Add a small “Forecast source” control (e.g. radio buttons or a select) with options:
                *   `Baseline (7-day average)`
                *   `AURORA v0.1 (experimental)`
            *   Display the currently active version and a short explanation/tooltip about AURORA being experimental.
        *   Keep the Forecasting tab view-only: it reflects whichever version is active but does not itself change planner logic.
    *   **Dependencies**: Rev 11 (planner respects `active_forecast_version`).

    **Sub-steps**

    *   [1] (Done) Ensure backend config APIs expose `forecasting.active_forecast_version` in both read and write paths.
    *   [2] (Done) Add a “Forecast source” control to the Settings page that reads/writes the active forecast version via the API and clearly labels AURORA as experimental.
    *   [3] (Done) Verify that toggling between baseline and AURORA via the Settings UI correctly updates config and, together with Rev 11, changes which forecasts the planner uses while preserving instant rollback.

    **Implementation**

    *   **Completed**:
        *   `/api/config` and `/api/config/save` already operate on the full `config.yaml` structure, so `forecasting.active_forecast_version` is transparently exposed and persisted without backend changes.
        *   Settings  UI tab now includes a “Forecasting” section with a `Forecast source` field bound to `forecasting.active_forecast_version`, with helper text marking `AURORA v0.1` as experimental.
        *   Changing this field and clicking **Save UI Preferences** posts a patch via `/api/config/save` that updates `forecasting.active_forecast_version`, which the planner now respects via Rev 11.

    *   **Acceptance Criteria**:
        *   Changing the forecast source in Settings correctly updates `forecasting.active_forecast_version` in `config.yaml` (via API).
        *   AURORA can be enabled/disabled without editing YAML or redeploying.
        *   Operators can switch back to baseline instantly if needed, completing the v0.3 story.

    **Sub-steps**

    *   [1] (Done) Ensure backend config APIs expose `forecasting.active_forecast_version` in both read and write paths.
    *   [2] (Done) Add a “Forecast source” control to the Settings page that reads/writes the active forecast version via the API and clearly labels AURORA as experimental.
    *   [3] (Done) Verify that toggling between baseline and AURORA via the Settings UI correctly updates config and, together with Rev 11, changes which forecasts the planner uses while preserving instant rollback.



---

## Phase 5: AURORA v0.4 — Weather & UX Refinement

### Rev 13 — 2025-11-18: AURORA Naming Cleanup & Forecast Toggle Placement *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Clean up AURORA naming in the UI (no hard-coded version suffixes) and move the forecast source toggle from Settings → UI into the Forecasting tab where it belongs.
*   **Started**: 2025-11-18
*   **Last Updated**: 2025-11-18

    **Plan**

    *   **Goals**:
        *   Make AURORA appear as a single evolving feature in the UI (no v0.1/v0.3 clutter).
        *   Place the “which forecast is active?” toggle in the Forecasting tab, closer to MAE and charts.

    *   **Scope**:
        *   Keep internal `forecast_version` keys versioned (e.g. `aurora`) for DB and config.
        *   Update UI labels so the AURORA option is simply called “AURORA (ML model, experimental)”.
        *   Move the forecast source dropdown from Settings → UI tab into the Forecasting page while still writing `forecasting.active_forecast_version` via `/api/config/save`.

    *   **Sub-steps**

    *   [1] (Done) Remove explicit `v0.1` suffixes from user-facing labels while keeping internal config/DB keys versioned (e.g. `aurora`).
    *   [2] (Done) Move the forecast source control from Settings → UI into the Forecasting page, keeping it wired to `forecasting.active_forecast_version` via `/api/config` and `/api/config/save`.
    *   [3] (Done) Verify that toggling Baseline vs AURORA from the Forecasting tab correctly updates config and still drives planner behaviour through Rev 11.

    **Implementation**

    *   **Completed**:
        *   UI labels now refer to “AURORA (ML model, experimental)” without exposing the internal version suffix; config and DB continue to use `baseline_7_day_avg` and `aurora` as `forecast_version` keys.
        *   The Settings → UI tab no longer owns the forecast source control; instead, the Forecasting tab exposes a “Planner forecast source” dropdown bound to `forecasting.active_forecast_version` via `/api/config` and `/api/config/save`.
        *   Switching the dropdown between “Baseline (7-day average)” and “AURORA (ML model, experimental)” updates `config.yaml` and, through Rev 11, changes which forecasts the planner consumes while preserving instant rollback.

### Rev 14 — 2025-11-18: Additional Weather Features *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Enrich AURORA with extra weather signals (beyond temperature) in training, evaluation, and forward inference.

    **Plan**

    *   **Goals**:
        *   Capture more of the weather impact on PV and load.
        *   Keep the feature set small and interpretable (1–2 extra signals).

    *   **Sub-steps**

    *   [1] (Done) Extend `ml/weather.py` to fetch additional hourly signals from Open-Meteo (cloud cover and shortwave radiation) for both historical and future windows.
    *   [2] (Done) Join these weather series into `ml/train.py` and `ml/evaluate.py`, adding new feature columns so models can use `cloud_cover_pct` and `shortwave_radiation_w_m2` alongside `temp_c`.
    *   [3] (Done) Wire the same features into `ml/forward.py` so forward AURORA forecasts use the enriched weather context.

    **Implementation**

    *   **Completed**:
        *   `ml/weather.get_weather_series` now returns a DataFrame with `temp_c`, `cloud_cover_pct`, and `shortwave_radiation_w_m2` where available, using the archive or forecast Open-Meteo API depending on the window.
        *   `ml/train.py` and `ml/evaluate.py` merge the weather DataFrame onto `slot_start` and include `cloud_cover_pct` and `shortwave_radiation_w_m2` as model features when present.
        *   `ml/forward.py` enriches future slots with the same weather columns and feeds them into the LightGBM models for forward AURORA forecasts.

### Rev 15 — 2025-11-18: Forecasting Tab Enhancements *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Refine the Forecasting tab to better illustrate Baseline vs AURORA behaviour using the existing metrics and forecasts.

    **Plan**

    *   **Goals**:
        *   Make it easier to visually compare Baseline vs AURORA.
        *   Keep changes incremental and focused on clarity.

    *   **Sub-steps**

    *   [1] (Done) Tidy up labels and legends in the Forecasting chart/table so Baseline and AURORA are clearly distinguished and use consistent naming with Rev 13.
    *   [2] (Done) Add a small summary block (e.g. last 7 days) highlighting MAE deltas between Baseline and AURORA using existing `/api/forecast/eval` data.
    *   [3] (Done) Ensure the Forecasting tab gracefully handles cases where AURORA forecasts are missing or disabled (clear messaging instead of empty charts).
    *   [4] (Done) Add lightweight “Run evaluation/forward” controls on the Forecasting tab that trigger backend endpoints to run `ml/evaluate.py` and `ml/forward.py` and then refresh metrics, so operators can update AURORA KPIs without using the CLI.

    **Implementation**

    *   **Completed**:
        *   Backend:
            *   `/api/forecast/run_eval` (POST) runs `ml.evaluate` with `--days-back` and returns a simple status JSON.
            *   `/api/forecast/run_forward` (POST) runs `ml.forward` to generate forward AURORA forecasts.
        *   Frontend:
            *   Forecasting tab adds two small buttons next to the planner source selector:
                *   “Run eval (7d)” → calls `Api.forecastRunEval(7)` then reloads `/api/forecast/eval` and `/api/forecast/day`.
                *   “Run forward (48h)” → calls `Api.forecastRunForward(48)` then reloads the same APIs.
            *   Buttons show simple “Running…” states and log errors to the console without breaking the page.
            *   Labels and legends clearly distinguish “Baseline (7-day average)” and “AURORA (ML model, experimental)” across the Forecasting chart, KPIs, and table.
            *   A compact MAE delta summary card shows how much AURORA improves or worsens MAE vs baseline for PV and load over the last evaluation window.
            *   When AURORA metrics are missing or disabled, the tab shows a small warning message instead of silently rendering empty or misleading series.

---

### Rev 16 — 2025-11-18: AURORA Calibration & Safety Guardrails *(Status: ✅ Completed)*

*   **Model**: Gemini
*   **Summary**: Investigate why AURORA behaves sensibly in MAE metrics but poorly when driving the planner, then calibrate the models and add safety guardrails so AURORA is safe and useful in shadow mode and, later, live mode.

    **Plan**

    *   **Goals**:
        *   Understand and fix the discrepancy between “good MAE” and “bad planner behaviour”.
        *   Ensure AURORA never produces obviously invalid forecasts (e.g. PV at night, unrealistically low load) for the planner horizon.
        *   Re-establish AURORA as a trustworthy shadow-mode signal before any new live cutover.

    *   **Scope**:
        *   Deep-dive into training vs forward distributions and where AURORA diverges most from baseline/actuals.
        *   Adjust model training and/or calibration so forward forecasts remain realistic across all hours.
        *   Add planner-side guardrails (clamps/blends) to prevent obviously unsafe forecasts from affecting decisions.

    *   **Sub-steps**

    *   [1] (Done) Perform a focused offline analysis comparing AURORA vs baseline vs actuals for both load and PV across time-of-day (using existing `slot_observations` and `slot_forecasts`), to identify where AURORA is under- or over-estimating most severely.
    *   [2] (Done) Calibrate the models and feature set based on these findings (e.g. enforce PV≈0 at night by construction, revisit weather features if they introduce pathologies, adjust LightGBM hyperparameters, or change targets/normalisation) and retrain.
    *   [3] (Done) Add planner-facing guardrails for forward inference (e.g. PV/load clamps, optional blending with baseline like `max(baseline, aurora)` or a weighted mix) so that even if AURORA drifts, it cannot produce obviously unsafe scheduling inputs.
    *   [4] (Done) Re-run evaluation and a small set of end-to-end planner runs (with AURORA in shadow mode) and update this document with the new behaviour and any remaining caveats before considering AURORA for live use again.

    **Implementation**

    *   **Analysis**:
        *   Confirmed that "Zero Bias" was caused by `slot_observations` defaulting to 0.0 when sensor data was missing (Recorder limit trap).
        *   `ml/train.py` was training on these zeros, dragging predictions down.
    *   **Solution**:
        *   Modified `ml/train.py` to strictly filter `load_kwh > 0.001` and lowered `min_samples` to allow training on recent valid data (Cold Start fix).
        *   Added Safety Guardrails to `ml/forward.py`: `Load > 0.01 kWh` and `Night PV = 0.0` (22:00–04:00).
    *   **Verification**:
        *   Retrained model showed MAE improvement (0.15 vs 0.22 Baseline).
        *   Verification script confirmed forward slots pass all safety checks.

        
###   Rev 17 — 2025-11-20: Stabilization: Fixed Phantom Charging, S-Index Horizon & DB Crashes *(Status: ✅ Completed)*

*   **Model**: Google Gemini Flash 2.0
*   **Summary**: Diagnosed and fixed negative load bias causing phantom charging, extended forecast horizon for S-index, and fixed DB writer column mismatch.
*   **Started**: 2025-11-20 17:00
*   **Last Updated**: 2025-11-20 23:33

**Plan**

*   **Goals**: Eliminate "excess_pv" charging during dark hours; Fix S-index sticking to base factor; Resolve HTTP 500 on DB write.
*   **Scope**: Planner logic, Input fetching, Learning Database, DB Writer.
*   **Dependencies**: `planner_learning.db`, Nordpool prices, Open-Meteo API.
*   **Acceptance Criteria**:
1. No charging scheduled during expensive peak hours without real PV.
2. S-index reacts dynamically to cold weather/deficits (factor > 1.5).
3. `schedule.json` writes to MariaDB without error.

**Sub-steps**

*   [1] Diagnose and clean "Ghost Data" (zero-load records) in Learning DB.
*   [2] Implement "Shield" in Planner to clamp adjusted load/PV to 0.0.
*   [3] Fix S-index logic: Clear DB locks and extend `inputs.py` forecast horizon.
*   [4] Debug and fix `db_writer.py` column mismatch causing DB crashes.

**Implementation**

*   **Completed**: All goals met.
*   **In Progress**: None.
*   **Blocked**: None.
*   **Next Steps**: Move debug scripts to `debug/` folder (see backlog).
*   **Technical Decisions**:
*   **Planner**: Added `.clip(lower=0.0)` to adjusted forecasts to prevent negative math artifacts.
*   **Inputs**: Decoupled "Daily Forecast Horizon" (7 days) from "Price Slot Horizon" (48h) to ensure S-index has data for Day 2-4.
*   **DB Writer**: Corrected `plan_history` insert columns; `SoC` was mapped to `PV` column, causing overflow errors.
*   **Files Modified**: `planner.py`, `inputs.py`, `db_writer.py`.
*   **Configuration**: Changed S-index to `mode: dynamic`, `base_factor: 1.5`.

**Verification**

*   **Tests Status**:
*   `verify_fix.py`: Passed (No phantom charging).
*   `diagnose_schedule.py`: Passed (S-index 2.0, PV positive).
*   `debug_db_write.py`: Passed (Rows inserted successfully).
*   **Known Issues**: Planner targets 86% instead of 100% for tomorrow; diagnosed as hardware limit (Inverter maxed out during the limited cheap window).
*   **Rollback Plan**: Revert `planner.py` / `inputs.py` to Rev 16 state (git).

**Scripts Created (for `debug/` folder)**
*   `debug_learning.py`: Inspects the SQLite DB for learned biases and stored S-index factors.
*   `find_ghost_data.py`: Scans DB for suspicious `0.0` load records causing negative bias.
*   `clean_ghost_data.py`: Deletes invalid zero-load records from SQLite.
*   `clear_s_index.py`: Sets stored S-index to NULL for today, forcing Planner to read `config.yaml`.
*   `debug_inputs.py`: Simulates a planner run to check how many days of forecast data `inputs.py` returns.
*   `debug_forecast_db.py`: Inspects the `slot_forecasts` table to count available future slots per day.
*   `populate_forecasts.py`: Forces a fetch of 7 days of forecast data (via Open-Meteo) and writes to DB.
*   `diagnose_schedule.py`: Parses `schedule.json` to analyze S-index debug data, forecast totals, and charging stop reasons.
*   `debug_db_write.py`: Simulates the backend DB write operation in terminal to expose tracebacks.
*   `debug_db_row_by_row.py`: Inserts schedule rows one-by-one to isolate specific bad data.
*   `check_json_health.py`: Scans `schedule.json` for NaN or Infinite values.
*   `debug_pv_values.py`: Scans `schedule.json` specifically for negative PV values.
*   `show_prices.py`: Prints a simple table of tomorrow's prices and "Cheap" status.

**Backlog items**
*   **[UI]** Add "Reset Learning for Today" button to clear cached S-index/metrics without CLI.
*   **[UI]** Add Solar Array configuration (azimuth, tilt, kwp) to the UI settings page.
*   **[Planner]** Implement "Dynamic Window Expansion" (Smart Thresholds): Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Ops]** Create `debug/` folder and move all diagnostic scripts there.
        
## Backlog / Post v0.1 Ideas

These items are intentionally out of scope for AURORA v0.1 but should be
considered for future revisions once the core pipeline is stable.

*   **Model lifecycle & monitoring**
    *   Track model drift and data quality signals (e.g. changes in usage
        patterns, missing sensors, or weather feed failures).

*   **Future experimentation**
    *   Explore multi-model or ensemble approaches (e.g. separate models per
        season or weekday/weekend).
    *   Evaluate alternative algorithms or architectures (e.g. temporal
        convolutional networks) using the same `slot_observations` /
        `slot_forecasts` schema and `forecast_version` abstraction.

*   **Deployment & Server Transfer (Ops)**
    *   **Status**: 📋 Planned
    *   **Why**: "we should probably transfer the data to the server when we push the AURORA version later."
    *   **Goal**: We need to move your code + the planner_learning.db (with its trained models and history) to your production server safely.

*   **Scheduled Retraining (Automation)**
    *   **Status**: 📋 Planned (Post v0.1 idea)
    *   **Why**: Right now, you train the model manually (python ml/train.py).
    *   **Goal**: Make Darkstar train itself automatically every Sunday night (for example), so it keeps getting smarter without you touching it.

