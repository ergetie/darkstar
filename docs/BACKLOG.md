# Darkstar Energy Manager: Backlog & Future

## ⏸️ On Hold

### Rev 63 — Export What-If Simulator (Lab Prototype)
*   **Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.
*   **Status:** On Hold (Prototype exists but parked for Kepler pivot).

## 🗂️ Backlog

## Rev XX - Complete settings inventory
**Goal:** Investigate discrepancy between settings page and config.yam/secrets.yaml. And implement normal/advanced settings mode. Settings page should be clean and the user should not need to open the config.yaml to do ANY settings!


### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
### Rev A27 — ML Training Scheduler (Catch-Up Logic)

**Goal:** Implement a robust "Catch-Up" scheduler for ML model retraining.
*   **Catch-Up Logic:** Instead of exact time matching, check if the last successful run is older than the most recent scheduled slot.
*   **Config:** Flexible `run_days` and `run_time` in `config.yaml`.
*   **Status:** In Progress.

## USER INPUT:** Might skip the "plan" tab all together!

### [Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

### 🖥️ UI & Dashboard
*   **[UI] Reset Learning**: Add "Reset Learning for Today" button to Settings/Debug to clear cached S-index/metrics without using CLI. (When is this used? Maybe scrap?)
*   **[UI] Chart Polish**:
    *   Render `soc_target` as a step-line series.
    *   Add zoom support (wheel/controls).
    *   Offset tooltips to avoid covering data points.
    *   Ensure price series includes full 24h history even if schedule is partial.
*   **[UI] Mobile**: Improve mobile responsiveness for Planning Timeline and Settings.

### [Rev A30(?)] Effekttariffer **: Needs brainstorming...

### ⚙️ Planner & Core
*   **[Core] Dynamic Window Expansion (Smart Thresholds)**: *Note: Rev 20 in Aurora v2 Plan claimed this was done, but validating if fully merged/tested.* Logic: Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Core] Enhanced PV Dump (Water Thermal Storage)**: When battery SoC=100% AND PV surplus > threshold, proactively heat water to `temp_max` in the planner (not just override). Currently only handled reactively via excess_pv_heating override. Planner should anticipate and schedule this.
*   **[Core] Sensor Unification**: Refactor `inputs.py` / `learning.py` to read *all* sensor IDs from `config.yaml` (`input_sensors`), removing the need for `secrets.yaml` to hold entity IDs. (THIS SHOULD ALREADY BE DONE! VERIFY!)
*   **[Core] HA Entity Config Consolidation**: Currently vacation mode, learning, and other features read HA entity state at runtime. Consider consolidating all HA-derived toggles into `config.yaml` with a single source of truth pattern (config file vs. HA entity override). (Brainstorm how to do this since toggle entities might be wanted in HA for automations etc, are toggles in both places possible?)

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## 🔜 Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
