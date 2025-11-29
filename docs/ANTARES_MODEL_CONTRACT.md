# Antares v1 Model Contract (Phase 3 / Rev 69)

This document defines the contract for the Antares v1 supervised models trained on
simulation episodes, and how they relate to the existing data schemas.

It is the reference for:

- What inputs and targets the v1 models use.
- How training runs are logged.
- Where model artifacts are stored for later loading.

## 1. Inputs and Targets

Antares v1 is a supervised MPC-imitator trained on the slot-level dataset returned
by `ml.api.get_antares_slots(dataset_version="v1")`.

### 1.1 Targets

Per slot, the current v1 models predict:

- `batt_charge_kwh` (float): energy charged into the battery in the slot.
- `batt_discharge_kwh` (float): energy discharged from the battery in the slot.
- `export_kwh` (float): energy exported to the grid in the slot.

Targets are derived from `slot_observations` joined with simulation schedules,
following `docs/ANTARES_EPISODE_SCHEMA.md`.

Battery targets are only trained on days where `data_quality_daily.status="clean"`
and `battery_masked=False`. For days labeled `mask_battery`, the dataset builder
sets `batt_charge_kwh` and `batt_discharge_kwh` to `None` and
`battery_masked=True`, and these rows are excluded when fitting battery models.

### 1.2 Features

Features are constructed from the v1 slot dataset as follows:

- Time features (from `slot_start`, local time):
  - `hour`, `day_of_week`, `month`, `is_weekend`
  - `hour_sin`, `hour_cos`
- Price and energy context:
  - `import_price_sek_kwh`
  - `export_price_sek_kwh`
  - `load_kwh`
  - `pv_kwh`
  - `import_kwh`
  - `soc_start_percent`
  - `soc_end_percent`
  - `battery_masked` (0/1)

Water heater (`water_kwh`) is treated as part of the aggregate load context and is
not a direct control target in v1.

## 2. Dataset and Split

The training dataset consists of slots from simulation episodes where:

- `system_id="simulation"`.
- `data_quality_daily.status` is `clean` or `mask_battery` (exclude days are
  dropped).

A time-based split is applied on `episode_date`:

- Earlier days (approximately the first 80% of calendar days in the window) form
  the training set.
- The most recent days (remaining ~20%) form the validation set.

Exact train/validation date bounds are recorded per run in
`antares_training_runs`.

## 3. Models and Artifacts

Rev 69 trains one LightGBM regressor per target:

- Model family: `lightgbm.LGBMRegressor`.
- Shared hyperparameters (subject to future tuning):
  - `n_estimators=200`
  - `learning_rate=0.05`
  - `subsample=0.8`
  - `colsample_bytree=0.8`
  - `random_state=42`

Models are saved in LightGBM native format under:

- Base directory: `ml/models/antares_v1/`
- Per-run directory:
  - `ml/models/antares_v1/antares_v1_<UTC_TIMESTAMP>_<RUN_ID_PREFIX>/`
- Per-target files:
  - `batt_charge_kwh.lgb`
  - `batt_discharge_kwh.lgb`
  - `export_kwh.lgb`

The training script `ml/train_antares.py` is the canonical entrypoint:

- Loads the v1 slot dataset (`get_antares_slots("v1")`).
- Builds features and applies the time-based split.
- Trains the three LightGBM models (where enough data is available).
- Saves artifacts under the per-run directory.

## 4. Training Run Logging

Each training run is logged to SQLite `data/planner_learning.db` in the table
`antares_training_runs`:

- `run_id` (TEXT, PRIMARY KEY): UUIDv4 string identifying the run.
- `created_at` (TEXT): UTC timestamp when logging occurred.
- `dataset_version` (TEXT): currently `"v1"`.
- `train_start_date` (TEXT, `YYYY-MM-DD`): first training day.
- `train_end_date` (TEXT, `YYYY-MM-DD`): last training day.
- `val_start_date` (TEXT, nullable): first validation day, if any.
- `val_end_date` (TEXT, nullable): last validation day, if any.
- `targets` (TEXT): comma-separated list of targets used in the run.
- `model_type` (TEXT): e.g. `"lightgbm_regressor"`.
- `hyperparams_json` (TEXT): JSON string with the hyperparameters used.
- `metrics_json` (TEXT): JSON string with per-target metrics and validation cost
  context.
- `artifact_dir` (TEXT): path to the directory containing the model files.

Per-target metrics currently include:

- `train_samples`
- `val_samples`
- `mae`
- `rmse`

Validation cost context logs baseline cost statistics computed from observed
`import_kwh`/`export_kwh` and prices over the validation window. Future revisions
may extend this to compare full simulated cost between MPC and Antares-driven
actions.

## 5. Usage Notes

- `ml/train_antares.py` should be invoked from the project root with:
  - `PYTHONPATH=. python ml/train_antares.py`
- The resulting `antares_training_runs` row and model directory are the single
  source of truth for which Antares v1 models were trained, on which data, and
  with which metrics.
- Later Antares phases (Gym/RL, shadow mode) should load models from the
  `artifact_dir` recorded in `antares_training_runs` rather than hard-coding
  paths.

## 6. Antares Gym Environment (Rev 70)

The Gym-style environment for simulation-based agents is implemented in
`ml/simulation/env.py` as `AntaresMPCEnv`.

- `reset(day)`:
  - `day` is a local calendar day (`YYYY-MM-DD` string, `datetime.date`, or
    `datetime`).
  - Uses `SimulationDataLoader` to build planner inputs and initial state, then
    runs the existing MPC planner to generate a full schedule for that day.
  - Initializes an internal pointer to the first slot and returns the initial
    state vector.
- `step(action)`:
  - Advances one slot along the MPC schedule and returns a `StepResult`:
    - `next_state`: NumPy array with:
      - hour-of-day
      - load forecast (kWh)
      - PV forecast (kWh)
      - projected SoC (%)
      - import price (SEK/kWh)
      - export price (SEK/kWh)
    - `reward`: scalar float, defined as negative net cost for the slot:
      `-(import_cost - export_revenue + battery_wear_cost)`.
    - `done`: `True` when the end of the day’s schedule is reached.
    - `info`: dict with metadata (`day`, slot index, etc.).
  - In Rev 70 the `action` argument is accepted but ignored; the environment
    always replays the deterministic MPC decisions.

Episodes:

- One episode corresponds to one historical day in the validated window
  (July–now), using the same data-quality gating as for simulation episodes.

This environment is the canonical interface for future Antares agents and RL
experiments; later revisions may extend the `action` handling to override MPC
decisions while keeping the same state/reward contract.

