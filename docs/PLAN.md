# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 64 — Antares Phase 1: Unified Data Collection (The Black Box)

**Goal:**
Initialize "Project Antares" (RL Agent) by creating a unified training dataset. Currently, our data is split between MariaDB (Actions) and SQLite (Observations). To train an AI, we need to capture the exact **State** ($S_t$) and **Action** ($A_t$) in a single snapshot at the moment of decision.

**Scope:**
1.  **Database Schema (SQLite)**: Create a new `training_episodes` table in `planner_learning.db` to store full JSON snapshots of every planning run.
2.  **The Black Box Logger**: Implement the logging logic in `learning.py` to serialize inputs and outputs.
3.  **Pollution Prevention**: Modify `planner.py` to accept a `record_training_episode` flag, ensuring only *real* automation runs log data, while UI/Lab simulations do not.

**Implementation Details:**
*   **Schema**:
    *   Table: `training_episodes`
    *   Columns: `episode_id` (UUID), `created_at` (Timestamp), `inputs_json` (The State: Prices, Forecasts, SoC), `context_json` (Strategy Flags: Vacation, Volatility), `schedule_json` (The Action: The full 48h plan), `config_overrides_json` (What Strategy Engine changed).
*   **`backend/learning.py`**:
    *   Add `log_training_episode(input_data, schedule_df, config_overrides)` method.
    *   Handle DataFrame serialization (ISO dates) and input sanitization.
*   **`planner.py`**:
    *   Update `generate_schedule` signature to accept `record_training_episode: bool = False`.
    *   Inject logging hook at the end of the generation process: `if record_training_episode and self._learning_enabled(): ...`
*   **Entry Points**:
    *   Update `backend/scheduler.py` (The Daemon) to call planner with `record_training_episode=True`.
    *   Update `bin/run_planner.py` (CLI Tool) to call planner with `record_training_episode=True`.
    *   Ensure `backend/webapp.py` (UI/Lab) continues using the default `False` to prevent data pollution.

**Verification Plan:**
1.  Run `python -m bin.run_planner`: Verify a new row appears in `training_episodes` with populated JSON fields.
2.  Open Web UI → Planning Lab → "Run Simulation": Verify **NO** new row appears in `training_episodes`.
3.  Check database size impact after 24h (verify it remains negligible).

### Rev 63 — Export What-If Simulator (Lab Prototype) (ongoing)

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
