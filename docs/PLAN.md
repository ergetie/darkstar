# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

(Antares revisions archived to CHANGELOG.md)

### Rev K2 — Kepler Promotion (Primary Planner)

**Goal:** Promote Kepler to be the primary planner, generating the official `schedule.json` used for device control.

**Scope / Design Decisions:**
*   **Config Switch:** Introduce `config.kepler.primary_planner` (bool) to toggle between Heuristic and Kepler.
*   **Planner Refactor:** Modify `planner.py` to delegate the main scheduling logic to `KeplerSolver` when enabled.
*   **UI Compatibility:** Ensure the generated schedule DataFrame has all columns expected by the frontend (e.g., `battery_charge_kw`, `projected_soc_percent`).

**Implementation Steps:**
1.  **Planner Delegation:**
    *   Modify `HeliosPlanner.generate_schedule` to check `config.kepler.primary_planner`.
    *   If true, call `run_kepler_primary` (new method) and return its result.
    *   `run_kepler_primary` should call `KeplerSolver`, then convert the result back to the standard DataFrame format using `adapter.py`.
2.  **Config Update:**
    *   Update `config.yaml` to include `kepler: { enabled: true, shadow_mode: true, primary_planner: false }` (initially false).
3.  **Verification:**
    *   **Dry Run:** Run with `primary_planner: true` locally and inspect `schedule.json`.
    *   **UI Check:** Verify the dashboard renders the Kepler schedule correctly.
    *   **Production Rollout:** Enable on the live system and monitor for 24h.

**Status:** Planned.

---

## Backlog

### ⏸️ On Hold

### Rev 63 — Export What-If Simulator (Lab Prototype)
*   **Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.
*   **Status:** On Hold (Prototype exists but parked for Kepler pivot).


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
