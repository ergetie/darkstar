# Antares Episode & Training Dataset Schema (Phase 2.5 / Rev 68)

This document defines the stable schema/contract for Antares v1 simulation episodes and the derived slot-level training dataset, as implemented in Phase 2.5 (Rev 68).

It is the canonical reference for:

- How `training_episodes` (SQLite / MariaDB) represent simulation runs.
- How episodes are linked back to `slot_observations` (SQLite).
- What features/targets are exposed to Antares v1.

## 1. Episode-Level Schema

Episodes are stored in:

- SQLite: `training_episodes`
- MariaDB: `antares_learning`

For simulation runs, `system_id="simulation"`.

### 1.1 Core Columns

- `episode_id` (TEXT / VARCHAR)
  - UUIDv4 string, primary key.
- `created_at` (TEXT / TIMESTAMP)
  - Insert timestamp (metadata only; not used for joins).
- `inputs_json` (TEXT / LONGTEXT)
  - JSON blob of planner inputs for this run.
- `context_json` (TEXT / LONGTEXT)
  - JSON blob with episode context, including:
    - `episode_start_local` (string, ISO 8601 with timezone, e.g. `2025-08-01T00:00:00+02:00`)
    - `episode_date` (string, `YYYY-MM-DD`, local calendar day)
    - `system_id` (string, e.g. `"simulation"`, `"prod"`)
    - `data_quality_status` (string, one of `"clean"`, `"mask_battery"`, `"exclude"`, `"unknown"`)
    - (Optional) any additional context for future phases.
- `schedule_json` (TEXT / LONGTEXT)
  - JSON blob with the planner schedule:
    - Top-level object:
      - `schedule`: list of per-slot dicts (see 2.1).
      - `meta`: planner metadata (planned_at timestamp, timezone, etc.).
- `config_overrides_json` (TEXT / LONGTEXT, nullable)
  - JSON blob of any dynamic config overrides applied by Strategy Engine (often `null` for baseline MPC).

### 1.2 Episode Identity & Joins

For Antares v1:

- Episodes are identified by:
  - `episode_id`
  - `episode_date`
  - `episode_start_local`
  - `system_id`
  - `data_quality_status`
- Episodes are linked to slot data via:
  - `schedule_json.schedule[*].start_time` (local ISO) → `slot_observations.slot_start` (local ISO, same format).

We **do not** use `created_at` for joins (it is metadata only).

## 2. Slot-Level Schedule Schema

Each `schedule_json.schedule[*]` entry is a dict with (most relevant) keys:

- `start_time` (string, ISO 8601 with timezone)
- `end_time` (string, ISO 8601 with timezone)
- `import_price_sek_kwh` (float)
- `export_price_sek_kwh` (float)
- `pv_forecast_kwh` (float)
- `load_forecast_kwh` (float)
- `adjusted_pv_kwh` (float)
- `adjusted_load_kwh` (float)
- `import_kwh` (float, where present)
- `export_kwh` (float, where present)
- `battery_charge_kw` (float, where present)
- `battery_discharge_kw` (float, where present)
- `projected_soc_percent` (float, where present)
- `projected_soc_kwh` (float, where present)
- `projected_battery_cost` (float, where present)
- `action` (string, planner action label, e.g. `"Charge"`, `"Discharge"`, `"Hold"`, `"PV Charge"`)

Not all fields are required for every training use case, but the above set is stable and available for simulation episodes.

## 3. Slot Observations Schema (Ground Truth)

Canonical slot-level ground truth is stored in SQLite `slot_observations`:

- `slot_start` (TEXT, ISO 8601 with timezone, local time, PRIMARY KEY)
- `slot_end` (TEXT, ISO 8601 with timezone)
- `import_kwh` (REAL)
- `export_kwh` (REAL)
- `pv_kwh` (REAL)
- `load_kwh` (REAL)
- `water_kwh` (REAL)
- `batt_charge_kwh` (REAL, nullable)
- `batt_discharge_kwh` (REAL, nullable)
- `soc_start_percent` (REAL, nullable)
- `soc_end_percent` (REAL, nullable)
- `import_price_sek_kwh` (REAL, nullable)
- `export_price_sek_kwh` (REAL, nullable)
- `executed_action` (TEXT, nullable)
- `quality_flags` (TEXT, nullable JSON-ish string)

Time representation:

- All `slot_start` / `slot_end` values are stored as local time with timezone offset (e.g. `2025-08-01T00:00:00+02:00`).
- Simulation episodes use the **same** local ISO strings in `schedule[*].start_time`.

## 4. Data Quality Labels

Data quality is tracked in `data_quality_daily` (SQLite):

- `date` (TEXT, `YYYY-MM-DD`, PRIMARY KEY)
- `status` (TEXT)
  - `"clean"`: load/PV/import/export match HA within tolerance; battery channels trustworthy.
  - `"mask_battery"`: grid/load/PV are good; battery charge/discharge may be unreliable.
  - `"exclude"`: day should not be used for Antares training (missing slots, severe mismatches, or SoC anomalies).
- Additional diagnostic columns (counts of bad hours, missing slots, etc.).

These labels are propagated into:

- `training_episodes.context_json.data_quality_status`
- The derived training dataset (`battery_masked` flag).

## 5. Derived Antares Training Dataset (Slot-Level)

Antares v1 training consumes a **per-slot** dataset constructed from:

- Simulation episodes (`training_episodes` / `antares_learning`).
- Slot observations (`slot_observations`).
- Data quality labels (`data_quality_daily`).

This dataset is built by `ml/simulation/dataset.py::build_antares_training_dataset` and exposed as a list of `AntaresSlotRecord` objects with fields:

- `episode_id` (str)
- `episode_date` (str, `YYYY-MM-DD`)
- `system_id` (str, typically `"simulation"`)
- `data_quality_status` (str: `"clean"`, `"mask_battery"`, `"exclude"`, `"unknown"`)
- `slot_start` (str, ISO 8601, local time)
- `import_price_sek_kwh` (float)
- `export_price_sek_kwh` (float)
- `load_kwh` (float)
- `pv_kwh` (float)
- `import_kwh` (float)
- `export_kwh` (float)
- `batt_charge_kwh` (float | None)
- `batt_discharge_kwh` (float | None)
- `soc_start_percent` (float | None)
- `soc_end_percent` (float | None)
- `battery_masked` (bool)

### 5.1 Inclusion Rules

- Only episodes with `system_id="simulation"` are considered.
- Only days with `data_quality_status`:
  - `"clean"` are always included.
  - `"mask_battery"` are included if `include_mask_battery=True` (default).
  - `"exclude"` days are **never** included in the dataset.

### 5.2 Battery Masking

- For days labeled `"mask_battery"`:
  - `batt_charge_kwh` and `batt_discharge_kwh` are set to `None`.
  - `battery_masked=True`.
- For `"clean"` days:
  - Battery flows are preserved as-is from `slot_observations`.

### 5.3 Join Contract

- Join key: `schedule_json.schedule[*].start_time` == `slot_observations.slot_start` (string equality).
- `episode_date` is used to join in `data_quality_daily.status`.
- Timezone: all timestamps are local ISO with offset; no conversion is required for joins.

## 6. Usage Notes

- For Antares v1:
  - Use `"clean"` days as primary training data.
  - Use `"mask_battery"` days for grid-/load-/PV-centric tasks, ignoring battery targets where `battery_masked=True`.
  - Exclude `"exclude"` days entirely from training.
- Future phases may extend the schema, but the fields and contracts described here should remain stable for backward compatibility.

