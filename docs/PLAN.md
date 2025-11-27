# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

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
