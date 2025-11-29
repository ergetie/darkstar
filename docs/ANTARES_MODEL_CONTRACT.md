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

**Phase 3 data window completeness (Rev 74):** The canonical Antares v1
dataset uses the July 2025 → latest validated date window from
`slot_observations` in `data/planner_learning.db`. Energy flows for this
window are validated against Home Assistant (via `data_quality_daily`), and
price data (import/export SEK/kWh) is backfilled and gap-fixed, including
late-November tail days where the recorder was not yet active. This window
is considered price- and energy-complete for Antares Phase 3 training and
evaluation.


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

## 7. Antares v1 Policy (Rev 72)

The first Antares v1 policy is a simple MPC-imitating model trained on state
vectors and MPC actions observed in `AntaresMPCEnv`.

- Training:
  - Script: `ml/train_antares_policy.py`.
  - For each eligible day (from `data_quality_daily` with `status in {clean, mask_battery}`):
    - Run `AntaresMPCEnv.reset(day)` to obtain the MPC schedule.
    - For each slot:
      - Build state vector via `AntaresMPCEnv._build_state_vector(row)`:
        `[hour_of_day, load_forecast_kwh, pv_forecast_kwh, projected_soc_percent, import_price, export_price]`.
      - Extract MPC actions:
        - `battery_charge_kw` (from `battery_charge_kw` or `charge_kw`).
        - `battery_discharge_kw`.
        - `export_kw`.
    - Train one LightGBM regressor per target on all collected `(state, action)` pairs.
  - Models are saved under:
    - `ml/models/antares_policy_v1/antares_policy_v1_<UTC_TIMESTAMP>_<RUN_ID_PREFIX>/`
    - Filenames:
      - `policy_battery_charge_kw.lgb`
      - `policy_battery_discharge_kw.lgb`
      - `policy_export_kw.lgb`
  - Runs are logged in SQLite `antares_policy_runs`:
    - `run_id` (TEXT, PRIMARY KEY)
    - `created_at` (TEXT, UTC timestamp)
    - `models_dir` (TEXT, path to the run directory)
    - `target_names` (TEXT, comma-separated list of targets)
    - `metrics_json` (TEXT, JSON with per-target training metrics)

- Inference:
  - Loader: `ml.policy.antares_policy.AntaresPolicyV1.load_from_dir(models_dir)`.
  - `AntaresPolicyV1.predict(state: np.ndarray) -> Dict[str, float]` expects the
    same 6-D state vector as `AntaresMPCEnv` and returns:
    - `battery_charge_kw`
    - `battery_discharge_kw`
    - `export_kw`

- Evaluation:
  - Script: `ml/eval_antares_policy.py`.
  - Reloads the latest `antares_policy_runs` entry, runs the policy for a sample
    of recent days via `AntaresMPCEnv`, and compares predicted actions to MPC
    actions using MAE/RMSE and relative error bars.

This policy is offline-only and does not yet influence live schedules; it is a
first “brain” to validate that we can learn a stable mapping from environment
state to MPC-like actions before introducing Oracle-guided targets or online RL.

## 8. Policy Action Overrides & Cost Evaluation (Rev 73)

Rev 73 extends the Gym environment and adds cost evaluation for Antares
policies.

- Environment action overrides:
  - `AntaresMPCEnv.step(action)` now accepts an optional `action` dict:
    - Keys (all optional):
      - `battery_charge_kw`
      - `battery_discharge_kw`
      - `export_kw`
    - Behaviour:
      - If `action` is `None` or not a dict, the env replays pure MPC decisions.
      - If provided, action values override the MPC slot flows for that step,
        after clamping to physical limits:
        - Non-negative.
        - Bounded by config `battery.max_charge_power_kw` /
          `battery.max_discharge_power_kw` and an internal export power limit
          (`min(system.grid.max_power_kw, system.inverter.max_power_kw)`).
        - Further clamped by an internal SoC tracker so that SoC stays within
          `[battery.min_soc_percent, battery.max_soc_percent]`.
      - Overrides are applied only for cost/reward and internal SoC; the
        underlying MPC schedule remains unchanged.

- Cost evaluation:
  - Script: `ml/eval_antares_policy_cost.py`.
  - For a configurable number of recent days:
    - Loads the latest policy from `antares_policy_runs`.
    - Runs three cost baselines per day:
      - MPC replay (no overrides) via `AntaresMPCEnv`.
      - Policy-driven rollouts (policy actions passed into `step(action)`).
      - Oracle cost, where `solve_optimal_schedule(day)` succeeds.
    - Prints per-day and aggregate cost comparisons:
      - `Policy vs MPC`
      - `MPC vs Oracle`
      - `Policy vs Oracle` on the subset with Oracle solutions.

These additions keep all policy experimentation strictly offline while providing
clear SEK-based benchmarks for how Antares policies perform relative to MPC
and the Oracle on historical data.

## 6. Antares RL Agent v1 (Rev 76 / Phase 4–5)

Rev 76 introduces the first real RL-based Antares policy on top of the same
environment and cost model. This section freezes the RL-facing contract so the
agent, shadow mode, and evaluators all agree on state, action, and reward.

### 6.1 RL State Vector (v1)

The Antares RL agent uses the same core information as `AntaresMPCEnv`, encoded
into a fixed-length numeric state vector `s_t` per slot:

- Time context:
  - `hour_of_day` (0–23, local time).
- Forecast context (for the slot being controlled):
  - `load_forecast_kwh`
  - `pv_forecast_kwh`
- Battery context:
  - `projected_soc_percent` (0–100), MPC’s projected SoC at the end of slot.
- Price context:
  - `import_price_sek_kwh`
  - `export_price_sek_kwh` (falls back to import price if missing).

The RL state layout for v1 is therefore:

```text
[hour_of_day,
 load_forecast_kwh,
 pv_forecast_kwh,
 projected_soc_percent,
 import_price_sek_kwh,
 export_price_sek_kwh]
```

Future revisions may append additional features (e.g. day-of-week, month,
weather), but those changes must be versioned (e.g. `rl_state_version=2`).

### 6.2 RL Action Space (v1)

The RL agent outputs a continuous action vector `a_t`:

- `battery_charge_kw`  (≥ 0)
- `battery_discharge_kw` (≥ 0)

For v1, export is **not** directly controlled by the RL policy:

- Export `export_kwh` remains whatever the planner schedule specifies for the slot.
- RL influences cost indirectly via charge/discharge decisions that affect
  grid import and battery usage; export behaviour follows the MPC plan.

These actions map directly to the override keys already used by
`AntaresMPCEnv.step`:

- `battery_charge_kw`: requested charge power into the battery.
- `battery_discharge_kw`: requested discharge power from the battery.

Actions are always clamped server-side before use:

- Per-slot power limits from battery config:
  - `max_charge_power_kw`
  - `max_discharge_power_kw`
- Export limit from inverter/grid config still applies to the underlying MPC
  schedule, but RL v1 does not change export directly.
- Mutual exclusivity:
  - If both charge and discharge are requested > 0, discharge is preferred and the
    smaller magnitude is zeroed.

These clamps are applied inside the environment / shadow runner and are not
optional for the RL policy.

### 6.3 RL Reward and Episodes

Episodes are one full historical or simulated day (96 slots):

- `reset()` selects a day from the `clean` / `mask_battery` window and replays
  the MPC schedule through `AntaresMPCEnv` to obtain prices, forecasts, and
  baseline context.
- `step(action)` applies the RL action (after clamping) and computes a reward
  based on the same cost model as the supervised evaluation:

Per-slot quantities:

- `grid_import_kwh` computed from forecast load/PV/water and battery flows.
- `import_price_sek_kwh`, `export_price_sek_kwh`.
- `export_kwh` from the MPC schedule (RL v1 does not change export directly).
- `charge_kwh`, `discharge_kwh` (from action).

Reward:

```text
r_t = - (import_cost_sek - export_revenue_sek + wear_cost_sek + penalties_t)
```

Where:

- `import_cost_sek = grid_import_kwh * import_price_sek_kwh`
- `export_revenue_sek = export_kwh * export_price_sek_kwh`
- `wear_cost_sek` uses the existing `battery_economics.battery_cycle_cost_kwh`
  and `(charge_kwh + discharge_kwh)`.
- `penalties_t` includes:
  - SoC breaches (projected SoC below `min_soc_percent`).
  - Unmet water-heating demand where water is modeled (same signal as in
    `_evaluate_schedule`).
  - Additional shaping used only for RL training (not evaluation):
    - Gentle penalty for discharging in "cheap" hours: if the slot import price
      is below a per-day threshold (80% of the median non-zero import price)
      and `battery_discharge_kw > 0`, a small extra cost term is added to
      discourage unnecessary cycling when electricity is cheap.

The episode terminates after the last slot for the day (`done=True`).

### 6.4 RL Artefacts and Runs

RL runs are logged in a dedicated SQLite table `antares_rl_runs`:

- `run_id` (TEXT, PRIMARY KEY): UUIDv4 for the RL run.
- `created_at` (TEXT): UTC timestamp.
- `algo` (TEXT): e.g. `ppo`, `sac`.
- `state_version` (TEXT): e.g. `rl_state_v1`.
- `action_version` (TEXT): e.g. `rl_action_v1`.
- `train_start_date` / `train_end_date` (TEXT): training window.
- `val_start_date` / `val_end_date` (TEXT, nullable): validation window.
- `hyperparams_json` (TEXT): RL hyperparameters.
- `metrics_json` (TEXT): training/validation reward and cost metrics.
- `artifact_dir` (TEXT): path under `ml/models/antares_rl_v1/...`.

RL model files are stored under:

- Base directory: `ml/models/antares_rl_v1/`
- Per-run directory:
  - `ml/models/antares_rl_v1/antares_rl_v1_<UTC_TIMESTAMP>_<RUN_ID_PREFIX>/`
- Contents:
  - RL library checkpoint (e.g. Stable-Baselines3 `.zip` file).
  - Any normalisation / scaler parameters needed for inference.

### 6.5 RL Policy in Shadow Mode

In Phase 4–5 the RL policy is only used in **shadow mode**:

- Backend planner hook builds the normal MPC schedule and then, if
  `antares.enable_shadow_mode` is true, runs a configured Antares policy type:
  - `shadow_policy_type: lightgbm` (existing supervised policy).
  - `shadow_policy_type: rl` (new RL policy).
- The RL policy wrapper exposes `.predict(state)` with the contract above and
shadow schedules are written to `antares_plan_history` with:
  - `system_id` suffix like `prod_shadow_rl_v1`.
  - `policy_run_id` from `antares_rl_runs`.

Shadow schedules never affect Home Assistant; they are purely for evaluation
and comparison against MPC and Oracle on real production days.
