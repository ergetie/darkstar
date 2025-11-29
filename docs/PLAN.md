# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 68 — Antares Phase 2b: Simulation Episodes & Gym Interface

**Goal:**
Turn the validated historical replay engine into a clean dataset and environment interface for Antares by (a) generating large-scale MPC simulation episodes on top of `slot_observations`, and (b) exposing a thin Gym-style wrapper around the deterministic simulator for future RL agents.

**Scope:**
1. **Simulation Episode Generation:**
   - Define a stable episode schema (day-level or horizon-level) for MPC runs (inputs, schedule, costs, metadata, `system_id="simulation"`).
   - Use `bin/run_simulation.py` over the validated July–Present window to generate a first large batch of MPC episodes, ensuring that only days with good HA-aligned telemetry are included.
2. **Environment Loader & API:**
   - Wrap the existing `ml/simulation/data_loader.py` and deterministic simulator into a small environment class with:
     - `reset(day)` → initial state for a chosen historical day.
     - `step(action)` → runs a 15-minute slot and returns `(next_state, reward, done, info)`.
   - Keep the state/action/reward spaces simple and documented, but focus this revision on wiring and data access, not on training a new agent.
3. **Data Quality Filters:**
   - Add simple filters/masks so obviously bad days (missing load/PV, corrupt spikes) are excluded from simulation runs and Gym episodes by default.
   - Document how to regenerate episodes if the underlying `slot_observations` window is cleaned or backfilled further.

**Verification Plan:**
1. Run `bin/run_simulation.py` across a multi-week window and confirm that:
   - The expected number of `system_id="simulation"` episodes appears in SQLite/MariaDB.
   - Sample episodes have state/action/price/load/PV trajectories consistent with `slot_observations` and HA.
2. Instantiate the Gym-style environment, call `reset(day)` and step through a full day with the MPC policy, verifying that cumulative reward and cost match the corresponding simulation episode.
3. Ensure downstream training scripts (`ml/train.py` / future `ml/train_antares.py`) can read the new episodes and environment without additional schema changes.

### Rev 67 — Antares Data Foundation: Live Telemetry & Backfill Verification

**Status:** Completed (Phase 2.5 data window ready for Antares)

**Goal:**
Ensure the data foundation for Antares is trustworthy by validating the live telemetry pipeline (SQLite + MariaDB) against Home Assistant and safely executing a full historical backfill without UTC/CEST artifacts.

**Scope (Final State):**
1. **Live Slot Observations (SQLite):**
   - Verified HA vs SQLite for multiple historical days (July–October); backfilled `slot_observations` now track HA Energy within ≈0.1–0.2 kWh per hour with correct UTC/CEST handling.
   - Confirmed that old “spiky/gappy” live data came from planner-coupled observations (irregular cadence), not arithmetic bugs.
   - Implemented and deployed the dedicated recorder loop (`backend.recorder`) that runs every 15 minutes (00/15/30/45) and calls `record_observation_from_current_state` independently of the planner, so all future live days are recorded at slot resolution.
2. **Historical Backfill Window (SQLite):**
   - Extended `bin/backfill_ha.py` to consume HA LTS for all inverter energy channels: load, PV, grid import/export, battery charge/discharge.
   - Ran a full backfill for the July → recent window using LTS for older days and `ml.data_activator.etl_cumulative_to_slots` for the last ~10 days and water heater.
   - Used `bin/explode_rows.py` and `bin/fix_load_gaps.py` to eliminate the old “only :00 rows” and hourly lumping issues.
   - Repaired rare missing-slot days (e.g. 2025-11-16) with a small repair helper, then re-ran backfill so all target days have 96 slots.
3. **Automated HA vs SQLite Validation (`data_quality_daily`):**
   - Added `debug/validate_ha_vs_sqlite_window.py` to:
     - Fetch HA LTS hourly `change` values for load/PV/import/export (+ battery optional).
     - Aggregate `slot_observations` to hourly sums for the same channels.
     - Classify each day as `clean`, `mask_battery`, or `exclude` based on hourly |DB − HA| > 0.2 kWh, missing slots, and SoC anomalies.
   - Persisted results into `data_quality_daily` in `planner_learning.db`:
     - Window: `2025-07-03` → `2025-11-28`.
     - Final counts: 138 `clean`, 10 `mask_battery`, 1 `exclude` (today / partial).
4. **MariaDB `antares_learning`:**
   - Confirmed that `created_at` jitter for `system_id="prod"` episodes is expected and that training should rely on episode/context timestamps instead.
   - Implemented a robust mirror helper (`debug/mirror_simulation_episodes_to_mariadb.py`) that replays simulation episodes from SQLite `training_episodes` into MariaDB when the DB has been offline.

### Rev 66 — Antares Phase 2: The Time Machine (Simulator)

**Goal:**
Build a historical replay engine that generates thousands of "Training Episodes" by running the Planner against past data (July 2025–Present). This creates the initial dataset needed to train the Antares AI.

**Scope:**
1.  **HA History Fetcher**: A dedicated WebSocket client (`ml/simulation/ha_client.py`) to fetch Long Term Statistics (LTS) for Load and PV from Home Assistant.
2.  **The Upsampler**: Logic to convert 1-hour historical data (HA & pre-Sept Nordpool) into the 15-minute resolution required by the Planner.
3.  **The Simulation Loop**: A script (`bin/run_simulation.py`) that:
    *   Iterates through a date range (e.g., `2025-07-01` to `2025-11-27`).
    *   Constructs the "State" for every 15 minutes (Price, Load, PV, Battery SoC).
    *   Runs `planner.generate_schedule(record_training_episode=True)`.
    *   Optionally applies "Data Augmentation" (e.g., +10% Load noise) to multiply the dataset size.

**Implementation Details:**
*   **`ml/simulation/ha_client.py`**:
    *   Async class to handle Auth and `recorder/statistics_during_period` requests.
    *   Caching mechanism (save fetched days to `data/cache/`) to avoid spamming HA.
*   **`ml/simulation/data_loader.py`**:
    *   Orchestrates fetching Prices (DB or Nordpool fallback) and Sensor Data (HA).
    *   Handles **Resolution Alignment**: 1h -> 15m upsampling.
*   **`bin/run_simulation.py`**:
    *   CLI arguments: `--start-date`, `--end-date`, `--scenarios` (number of augmented runs per day).
    *   Sets `system_id="simulation"` so these runs are distinct from "prod".

**Verification Plan:**
1.  Run `python -m bin.run_simulation --start-date 2025-08-01 --end-date 2025-08-02`.
2.  Check MariaDB/SQLite for ~96 new rows with `system_id="simulation"`.
3.  Verify the `inputs_json` in the DB matches the historical data (approx. 0.2 kWh load per hour).


### Rev 65 — Antares Phase 1b: The Data Mirror

**Goal:**
Enable centralized data collection. While SQLite (local) is the safety buffer, we need a "Live Feed" of training data from the Production Server to the Development Environment. We will implement a "Mirror" that pushes training episodes to a central MariaDB table (`antares_learning`) tagged with a `system_id`.

**Scope:**
1.  **Configuration**: Add `system_id` to `config.yaml` to identify the data source (e.g., "prod" vs "dev").
2.  **MariaDB Schema**: Create `antares_learning` table in the central database (mirroring the SQLite structure + `system_id`).
3.  **Mirror Logic**: Update `learning.py` to dual-write: always to SQLite, and optionally to MariaDB if secrets are available.

**Implementation Details:**
*   **`config.yaml`**:
    *   Add `system.system_id` (Default: "dev").
*   **`backend/learning.py`**:
    *   Update `log_training_episode`:
        *   Load `secrets.yaml`.
        *   Check for `mariadb` credentials.
        *   If present, connect using `pymysql`.
        *   Execute `CREATE TABLE IF NOT EXISTS antares_learning (...)` (Schema: same as `training_episodes` but add `system_id VARCHAR(50)`).
        *   Insert the episode data with the configured `system_id`.
        *   Wrap in try/except to ensure MariaDB outages do not crash the local planner.

**Verification Plan:**
1.  Add `system_id: "dev"` to local config.
2.  Run `python -m bin.run_planner` locally.
3.  Check local SQLite: Row exists.
4.  Check MariaDB (via CLI or GUI): Row exists in `antares_learning` with `system_id="dev"`.
5.  (Later) Deploy to Server, set `system_id: "prod"`, and verify "prod" rows appear in MariaDB.


### Rev 64 — Antares Phase 1: Unified Data Collection (The Black Box)

**Status:** Completed

**Summary:**
- Added the `training_episodes` schema and a resilient `LearningEngine.log_training_episode` helper to persist sanitized input/context/schedule JSON payloads with UUID identifiers.
- Extended `HeliosPlanner.generate_schedule` with a `record_training_episode` flag, wired it into the CLI/daemon entry points, and kept web UI runs clean of production telemetry.
- Touched up `etl_cumulative_to_slots` gap handling plus the associated learning tests so the suite accurately validates the revised data flow.

**Implementation Details:**
*   **Schema**:
    *   Table: `training_episodes`
    *   Columns: `episode_id` (UUID), `created_at` (Timestamp), `inputs_json` (The State: Prices, Forecasts, SoC), `context_json` (Strategy Flags: Vacation, Volatility), `schedule_json` (The Action: The full 48h plan), `config_overrides_json` (What Strategy Engine changed).
*   **`backend/learning.py`**:
    *   Added `log_training_episode(input_data, schedule_df, config_overrides)` with careful serialization and sanitization of pandas objects.
    *   Ensured ETL gap detection tracks null slots and filters spike suppression around them so cumulative deltas stay accurate.
*   **`planner.py`**:
    *   Added the `record_training_episode` flag, saving episodes only when requested and learning is enabled.
*   **Entry Points**:
    *   Both `backend/scheduler.py` and `bin/run_planner.py` now pass `record_training_episode=True` during automation runs.
    *   `backend/webapp.py` keeps the flag at `False` to prevent Lab simulations from polluting training records.

**Verification Plan:**
1.  Run `python -m bin.run_planner`: record training episodes for real scheduler runs.
2.  Use the Planning Lab simulation: confirm no `training_episodes` rows appear.
3.  Monitor DB size over 24h to ensure the new table stays lightweight.

### Rev 63 — Export What-If Simulator (Lab Prototype) (ongoing/on hold)

**Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.

**Scope:**
*   Add a debug tool (`debug/test_export_scenarios.py`) that:
    *   Uses the Learning engine’s `DeterministicSimulator` and `simulate_schedule` to re-run a **full day** (00:00–24:00) through the planner.
    *   Applies progressively stronger “export at peaks” manual plans across the highest-price slots, re-simulating the whole horizon each time.
    *   Computes full-horizon cashflow metrics (grid import cost, export revenue, battery wear) for baseline vs scenarios using the existing `_evaluate_schedule` cost model.
    *   Reports target vs realized export energy and net SEK deltas vs baseline for each scenario (prototype for Lab “Export What-If”).
*   Planner core logic stays untouched; all what-if behaviour is driven via `prepare_df` → `apply_manual_plan` → `simulate_schedule`.

**Current status:** Prototype script is in place and structurally correct, but with today’s conservative export economics most scenarios still realize ≈0 kWh of extra export (planner chooses to hold), so the tool currently acts as a “sanity check” rather than a tuner.

**Next:** Switch the simulator to use **live Nordpool + Aurora forecasts** for an arbitrary day (not just data persisted in `planner_learning.db`), and add a dedicated “relaxed economics” mode (lower cycle cost / profit margin bounds) so the Lab UI can explore truly hypothetical export behaviour without changing production guardrails.

### Rev XX - PUT THE NEXT REVISION ABOVE THIS LINE!

---

## Backlog

### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
*   **[Rev A27] Scheduled Retraining**: Automate `ml/train.py` execution (e.g., weekly) to keep Aurora models fresh without manual intervention. Similar to Rev 57!
*   **[Rev A28] The Analyst (Expansion)**: Add "Grid Peak Shaving" capability—detect monthly peaks and force-discharge battery to cap grid import fees.
*   **[Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

### 🖥️ UI & Dashboard
*   **[UI] Reset Learning**: Add "Reset Learning for Today" button to Settings/Debug to clear cached S-index/metrics without using CLI.
*   **[UI] Chart Polish**:
    *   Render `soc_target` as a step-line series.
    *   Add zoom support (wheel/controls).
    *   Offset tooltips to avoid covering data points.
    *   Ensure price series includes full 24h history even if schedule is partial.
*   **[UI] Mobile**: Improve mobile responsiveness for Planning Timeline and Settings.

### ⚙️ Planner & Core
*   **[Core] Dynamic Window Expansion (Smart Thresholds)**: *Note: Rev 20 in Aurora v2 Plan claimed this was done, but validating if fully merged/tested.* Logic: Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Core] Sensor Unification**: Refactor `inputs.py` / `learning.py` to read *all* sensor IDs from `config.yaml` (`input_sensors`), removing the need for `secrets.yaml` to hold entity IDs.

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
