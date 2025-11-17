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

### Rev 7 — 2025-11-16: Modify `inputs.py` for AURORA Integration *(Status: 📋 Planned)*

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

### Rev 8 — 2025-11-16: Finalization and Cleanup *(Status: 📋 Planned)*

*   **Model**: Gemini
*   **Summary**: Finalize AURORA integration, update documentation, and remove deprecated code.
*   **Started**: 2025-11-16
*   **Last Updated**: 2025-11-17

    **Plan**

    *   **Goals**:
        *   Fully integrate AURORA into the Darkstar project.
    *   **Scope**:
        *   Update `docs/implementation_plan.md` with a summary of AURORA's implementation.
        *   Remove the old 7-day average forecasting logic from `inputs.py`.
        *   Update `README.md` with information about AURORA.
    *   **Dependencies**: AURORA fully integrated and stable (Rev 7).
    *   **Acceptance Criteria**:
        *   `docs/implementation_plan.md` reflects AURORA's successful integration.
        *   Project documentation is current.
