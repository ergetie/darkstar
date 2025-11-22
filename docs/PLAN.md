# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 56 — Dashboard Server Plan Visualization *(Status: 🔍 Validation Pending)*
*   **Goal**: Allow the Dashboard to visualize the *actual* server-side plan (`current_schedule` from DB) alongside the local `schedule.json` plan, ensuring operators can verify exactly what the system is executing.
*   **Current State**:
    *   Frontend: "Load server plan" button fetches `/api/db/current_schedule`.
    *   Backend: Endpoint merges execution history for "today" slots.
    *   **Missing**: Final verification that the merged data correctly aligns SoC Actuals and executed series without mutating the local plan file.
*   **Next Steps**:
    1.  Verify the "Server" badge appears correctly in the UI.
    2.  Confirm `soc_actual_percent` renders on the server plan view.
    3.  Mark as Completed in `CHANGELOG.md` once validated.

### Rev 57 — In-App Scheduler Orchestrator *(Status: 🏗️ Implementation Pending)*
*   **Goal**: Eliminate external `systemd`/`cron` dependencies. Move automation into a dedicated Python process (`backend/scheduler.py`) controlled by `config.yaml`.
*   **Design (Completed in previous Plan)**:
    *   Process: Dedicated `backend.scheduler` process.
    *   Config: `automation.schedule.every_minutes` (default 60).
    *   Status: `/api/scheduler/status` returning `next_run_at`, `last_run_status`.
    *   UI: Dashboard "Planner Automation" card shows health/next run.
*   **Implementation Steps**:
    1.  **Backend**: Implement `backend/scheduler.py` loop (load config → sleep → run planner → write status json).
    2.  **API**: Implement `/api/scheduler/status` to read the status JSON.
    3.  **UI**: Wire Dashboard card to the new API.
    4.  **Migration**: Update README/AGENTS.md to deprecate systemd timers.

### Rev A24 — The Weather Strategist (Strategy Engine) *(Status: 📋 Planned)*
*   **Goal**: Enhance the Strategy Engine to manipulate S-Index *Weights* based on forecast uncertainty, not just the base factor.
*   **Logic**:
    *   Analyze `cloud_cover_variance` and `temperature_variance` from Aurora inputs.
    *   If variance is high (uncertainty), increase `pv_deficit_weight` (conservative mode).
    *   If temperature variance is high, increase `temp_weight`.
*   **Scope**:
    *   `ml/weather.py`: Calculate variance metrics.
    *   `backend/strategy/engine.py`: Logic to output dynamic weights.
    *   `planner.py`: Accept weight overrides from the strategy engine.

### Rev 58 - PUT THE NEXT REVISION HERE! DO NOT CONTINUE ON "A" REVISIONS!

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