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

**Status:** Completed.

### Rev K3 — Strategic S-Index (Decoupled Strategy)

**Goal:** Implement a robust risk management strategy that balances intra-day safety with inter-day optimization.

**Scope:**
*   **Decoupled Strategy:**
    *   **Load Inflation:** Static `base_factor` (e.g., 1.1x) for D1 forecast error safety.
    *   **Target SoC:** Dynamic Hard Constraint based on D2/D3 risk (Temperature/PV).
*   **Dynamic Target SoC:** `Target % = Min % + (Risk - 1.0) * Scaling`.
*   **UI:** Display S-Index and Target SoC on dashboard.

**Status:** Completed.

### Rev K4 — Kepler Vision & Benchmarking

**Goal:** Further refine Kepler and benchmark its performance against legacy MCP.

**Scope:**
*   **Benchmarking:** Compare MCP vs Kepler plans for Today and Tomorrow.
*   **Kepler Vision:** Implement features from `KEPLER_VISION.md`.
*   **Refinement:** Tune S-Index parameters based on real-world data.

**Status:** Completed.

### Rev K5 — Strategy Engine Expansion (The Tuner)

**Goal:** Empower the Strategy Engine to dynamically tune all key Kepler parameters (`wear_cost`, `ramping_cost`, `export_threshold`) based on context.

**Scope:**
*   **Kepler Solver:** Expose `wear_cost`, `ramping_cost`, `export_threshold` as runtime arguments in `solve()`.
*   **Strategy Engine:** Implement logic to override these parameters based on context (e.g., Price Volatility, Grid Constraints).
*   **Integration:** Ensure `planner.py` -> `adapter.py` -> `KeplerSolver` pipeline passes these overrides correctly.

**Implementation Steps:**
1.  **Solver Update:** Modify `KeplerSolver` to accept and use parameter overrides.
2.  **Strategy Logic:** Add new rules to `StrategyEngine` (e.g., "High Price Spread -> Lower Export Threshold").
3.  **Wiring:** Update `adapter.py` to map strategy output to solver inputs.
4.  **Verification:** Verify that changing context (e.g., via mock) alters the solver's internal parameters and resulting schedule.

**Status:** Completed.

### Rev K6 — The Learning Engine (Metrics & Feedback)

**Goal:** Close the loop by measuring "Plan vs Actual" performance to enable data-driven tuning of the Strategy Engine.

**Scope:**
*   **Metrics:** Track `forecast_error`, `cost_deviation`, and `battery_efficiency_realized`.
*   **Persistence:** Store daily metrics in `planner_learning.db`.
*   **Feedback:** Use these metrics to auto-adjust `s_index` or `wear_cost` baselines (Phase 3).

**Status:** Completed.
**Outcome:** `planner_learning.db` now tracks planned vs actuals.

### Rev K7 — The Mirror (Backfill & Visualization)

**Goal:** Ensure data continuity and visualize performance.

**Scope:**
*   Implement auto-backfill from HA on startup.
*   Create "Performance" tab in Web UI (SoC Tunnel, Cost Reality).

**Status:** Completed.

### Rev K8 — The Analyst (Grid Peak Shaving)

**Goal:** Implement "Grid Peak Shaving" to cap grid import peaks, avoiding high power tariffs or blown fuses.

**Scope:**
*   **Config:** Add `grid.import_limit_kw` (e.g., 11.0).
*   **Kepler:** Add hard constraint `grid_import_t <= limit`.
*   **Strategy:** Allow dynamic adjustment of this limit (e.g., "Vacation Mode" might lower it, or "Emergency" might raise it).

**Status:** Completed.

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
