# Darkstar Energy Manager: Active Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Revision Naming Conventions

| Prefix | Area | Examples |
|--------|------|----------|
| **K** | Kepler (MILP solver) | K1-K19 |
| **E** | Executor | E1 |
| **A** | Aurora (ML) | A25-A29 |
| **H** | History/DB | H1 |
| **O** | Onboarding | O1 |
| **UI** | User Interface | UI1, UI2 |
| **F** | Fixes/Bugfixes | F1 |

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is a **chronological stream**. Newest items are at the **bottom**.
    
2.  **No Reordering:** Never move items. Only update their status or append new items.
    
3.  **Status Protocol:**
    
    -   Update the status tag in the Header: `### [STATUS] Rev ID — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template


```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

* [ ] Step 1
* [ ] Step 2

```

---

## 📜 Revision Stream

### [OBSOLETE] Rev K20 — Stored Energy Cost for Discharge

Goal: Make Kepler consider stored energy cost in discharge decisions.

Reason: Superseded by Rev K24. We determined that using historical cost in the solver constitutes a "Sunk Cost Fallacy" and leads to suboptimal future decisions. Cost tracking will be handled for reporting only.

### [DONE] Rev F2 — Wear Cost Config Fix

Goal: Fix Kepler to use correct battery wear/degradation cost.

Problem: Kepler read wear cost from wrong config key (learning.default_battery_cost_sek_per_kwh = 0.0) instead of battery_economics.battery_cycle_cost_kwh (0.2 SEK).

Solution:

1.  Fixed `adapter.py` to read from correct config key.
    
2.  Added `ramping_cost_sek_per_kw: 0.05` to reduce sawtooth switching.
    
3.  Fixed adapter to read from kepler config section.

### [DONE] Rev O1 — Onboarding & System Profiles

Goal: Make Darkstar production-ready for both standalone Docker AND HA Add-on deployments with minimal user friction.

Design Principles:

1.  **Settings Tab = Single Source of Truth** (works for both deployment modes)
    
2.  **HA Add-on = Bootstrap Helper** (auto-detects where possible, entity dropdowns for sensors)
    
3.  **System Profiles** via 3 toggles: Solar, Battery, Water Heater
    

**Phase 1: HA Add-on Bootstrap**

-   [x] **Auto-detection:** `SUPERVISOR_TOKEN` available as env var (no user token needed). HA URL is always `http://supervisor/core`.
    
-   [x] **Config:** Update `hassio/config.yaml` with entity selectors.
    
-   [x] **Startup:** Update `hassio/run.sh` to auto-generate `secrets.yaml`.
    

**Phase 2: Settings Tab — Setup Section**

-   [x] **HA Connection:** Add section in Settings → System with HA URL/Token fields (read-only in Add-on mode) and "Test Connection" button.
    
-   [x] **Core Sensors:** Add selectors for Battery SoC, PV Production, Load Consumption.
    

**Phase 3: System Profile Toggles**

-   [x] **Config:** Add `system: { has_solar: true, has_battery: true, has_water_heater: true }` to `config.default.yaml`.
    
-   [x] **UI:** Add 3 toggle switches in Settings → System.
    
-   [x] **Logic:** Backend skips disabled features in planner/executor.
    

Phase 4: Validation

| Scenario | Solar | Battery | Water | Expected |
|---|---|---|---|---|
| Full system | ✓ | ✓ | ✓ | All features |
| Battery only | ✗ | ✓ | ✗ | Grid arbitrage only |
| Solar + Water | ✓ | ✗ | ✓ | Cheap heating, no battery |
| Water only | ✗ | ✗ | ✓ | Cheapest price heating |

## [DONE] Rev UI1 — Dashboard Quick Actions Redesign

**Goal:** Redesign the Dashboard Quick Actions for the native executor, with optional external executor fallback in Settings.

**Implementation Status (2025-12-26):**
-   [x] Phase 1: Implement new Quick Action buttons (Run Planner, Executor Toggle, Vacation, Water Boost).
-   [x] Phase 2: Settings Integration
    -   [x] Add "External Executor Mode" toggle in Settings → Advanced.
    -   [x] When enabled, show "DB Sync" card with Load/Push buttons.
    
**Phase 3: Cleanup**

-   [x] Hide Planning tab from navigation (legacy).
-   [x] Remove "Reset Optimal" button.

    

### [DONE] Rev UI2 — Premium Polish

Goal: Elevate the "Command Center" feel with live visual feedback and semantic clarity.

**Implementation Status (2025-12-26):**
- [x] **Executor Sparklines:** Integrated `Chart.js` into `Executor.tsx` to show live trends for SoC, PV, and Load.
- [x] **Aurora Icons:** Added semantic icons (Shield, Coffee, GraduationCap, etc.) to `ActivityLog.tsx` for better context.
- [x] **Sidebar Status:** Implemented the connectivity "pulse" dot and vertical versioning in `Sidebar.tsx`.
- [x] **Dashboard Visuals (Command Cards):** Refactored the primary KPI area into semantic "Domain Cards" (Grid, Resources, Strategy).
- [x] **Control Parameters Card:**
    - [x] **Merge:** Combined "Water Comfort" and "Risk Appetite" into one card.
    - [x] **Layout:** Selector buttons (1-5) use **full width** of the card.
    - [x] **Positioning:** Card moved **UP** to the primary row.
    - [x] **Overrides:** Added "Water Boost (1h)" and "Battery Top Up (50%)" manual controls.
    - [x] **Visual Flair:** Implemented "Active Reactor" glowing states and circuit-board connective lines.
- [x] **Cleanup:** 
    - [x] Removed redundant titles ("Quick Actions", "Control Parameters") to save space.
    - [x] Implemented **Toolbar Card** for Plan Badge (Freshness + Next Action) and Refresh controls.
- [x] **HA Event Stream (E1):** Implement **WebSockets** to replace all polling mechanisms. 
    - **Scope:** Real-time streaming for Charts, Sparklines, and Status.
    - **Cleanup:** Remove the "30s Auto-Refresh" toggle and interval logic entirely. Dashboard becomes fully push-based.
- [x] **Data Fix (Post-E1):** Fixed - `/api/energy/today` was coupled to executor's HA client. Refactored to use direct HA requests. Also fixed `setAutoRefresh` crash in Dashboard.tsx.

## [DONE] Rev K21 — Water Heating Spacing & Tuning

**Goal:** Fix inefficient water heating schedules (redundant heating & expensive slots).

**Implementation Status (2025-12-26):**
-   [x] **Soft Efficiency Penalty:** Added `water_min_spacing_hours` and `water_spacing_penalty_sek` to `KeplerSolver`. 
-   [x] **Progressive Gap Penalty:** Implemented a two-tier "Rubber Band" penalty in MILP to discourage very long gaps between heating sessions.
-   [x] **UI Support:** Added spacing parameters to Settings → Parameters → Water Heating.



## [DONE] Rev K22 — Plan Cost Not Stored

**Goal:** Fix missing `planned_cost_sek` in Aurora "Cost Reality" card.

**Implementation Status (2025-12-26):**
-   [x] **Calculation:** Modified `planner/output/formatter.py` and `planner/solver/adapter.py` to calculate Grid Cash Flow cost per slot.
-   [x] **Storage:** Updated `db_writer.py` to store `planned_cost_sek` in MariaDB `current_schedule` and `plan_history` tables.
-   [x] **Sync:** Updated `backend/learning/mariadb_sync.py` to synchronize the new cost column to local SQLite.
-   [x] **Metrics:** Verified `backend/learning/engine.py` can now aggregate planned cost correctly for the Aurora dashboard.

### [OBSOLETE] Rev K23 — SoC Target Holding Behavior (2025-12-22)

**Goal:** Investigate why battery holds at soc_target instead of using battery freely.

**Reason:** Issue no longer reproduces after Rev K24 (Battery Cost Separation) was implemented. The decoupling of accounting from trading resolved the underlying constraint behavior.

### [DONE] Rev K24 — Battery Cost Separation (Gold Standard)



**Goal:** Eliminate Sunk Cost Fallacy by strictly separating Accounting (Reporting) from Trading (Optimization).



**Architecture:**



1.  **The Accountant (Reporting Layer):**

    *   **Component:** `backend/battery_cost.py`

    *   **Responsibility:** Track the Weighted Average Cost (WAC) of energy currently in the battery.

    *   **Usage:** Strictly for UI/Dashboard (e.g., "Current Battery Value") and historical analysis.

    *   **Logic:** `New_WAC = ((Old_kWh * Old_WAC) + (Charge_kWh * Buy_Price)) / New_Total_kWh`



2.  **The Trader (Optimization Layer):**

    *   **Component:** `planner/solver/kepler.py` & `planner/solver/adapter.py`

    *   **Responsibility:** Determine optimal charge/discharge schedule.

    *   **Constraint:** Must **IGNORE** historical WAC.

    *   **Drivers:**

        *   **Opportunity Cost:** Future Price vs. Current Price.

        *   **Wear Cost:** Fixed cost per cycle (from config) to prevent over-cycling.

        *   **Terminal Value:** Estimated future utility of energy remaining at end of horizon (based on future prices, NOT past cost).



**Implementation Tasks:**

* [x] **Refactor `planner/solver/adapter.py`:**

    *   Remove import of `BatteryCostTracker`.

    *   Remove logic that floors `terminal_value` using `stored_energy_cost`.

    *   Ensure `terminal_value` is calculated solely based on future price statistics (min/avg of forecast prices).

* [x] **Verify `planner/solver/kepler.py`:** Ensure no residual references to stored cost exist.

### [DONE] Rev F3 — Water Heater Config & Control

**Goal:** Fix ignored temperature settings.

**Problem:** User changed `water_heater.temp_normal` from 60 to 40, but system still heated to 60.

**Root Cause:** Hardcoded values in `executor/controller.py`:
```python
return 60  # Was hardcoded instead of using config
```

**Implementation (2025-12-27):**
- [x] **Fix:** Updated `controller.py` to use `WaterHeaterConfig.temp_normal` and `temp_off`.
- [x] **Integration:** Updated `make_decision()` and `engine.py` to pass water_heater_config.

### [PLANNED] Rev F4 — Entity Safety & Global Error Handling

**Goal:** Prevent application crashes due to missing HA entities and provide user-friendly error feedback.

**Problem:**
* Missing entities (e.g., renamed in HA) might currently cause unhandled exceptions in `recorder.py` or `ha_client.py`, potentially crashing the backend loop.
* The UI likely fails silently or breaks layout when data is missing, instead of guiding the user.

**Investigation Plan:**
* [ ] **Crash Test:** Temporarily rename a critical entity in `config.default.yaml` to a non-existent one and observe logs/container stability.
* [ ] **Code Audit:** Check `backend/recorder.py` and `planner/inputs/data_prep.py` for error handling around `hass.get_state()`.
* [ ] **Frontend Audit:** Check how `Dashboard.tsx` handles `undefined` API responses.

**Implementation Plan:**
* [ ] **Backend Hardening:**
    * Wrap HA API calls in `try/except` blocks.
    * Implement a "Health Check" system that validates all configured entities on startup.
    * Expose health status via API (e.g., `/api/health` or part of `/api/status`).
* [ ] **Frontend "Red Alert":**
    * Create a global `SystemAlert` component (Banner).
    * If `health.missing_entities` is non-empty, show: "Critical: Entities not found [list]. Check HA connection."
* [ ] **Graceful Degradation:** Ensure Planner/Executor skips logic dependent on missing sensors rather than crashing.

### [PLANNED] Rev F5 — Fix Planner Crash on Missing 'start_time'

**Goal:** Fix `KeyError: 'start_time'` crashing the planner when processing schedule dataframes.

**Error Analysis:**
* **Log:** `File "/app/planner/output/formatter.py", line 42, in dataframe_to_json_response start_series = pd.to_datetime(df_copy["start_time"], errors="coerce")` -> `KeyError: 'start_time'`
* **Root Cause:** The `schedule_df` passed to `dataframe_to_json_response` is missing the `start_time` column. This implies `kepler.solve()` or `adapter.py` returned a DataFrame where the index (usually `start_time`) was not reset to a column, or the column was dropped/renamed.

**Investigation Plan:**
* [ ] **Trace `planner/output/schedule.py`:** Check where `schedule_df` comes from.
* [ ] **Inspect `planner/solver/adapter.py`:** Verify the DataFrame structure returned by `solve()`. Does it have `start_time` as an index or column?
* [ ] **Check `pipeline.py`:** See if any intermediate steps modify the DataFrame columns before saving.

**Implementation Plan:**
* [ ] **Defensive Coding:** In `formatter.py`, check if `start_time` is in `df.columns`. If not, and it's in the index, run `df.reset_index(inplace=True)`.
* [ ] **Validation:** Add a `verify_schedule_schema(df)` step in `pipeline.py` to catch malformed DataFrames early.

### NEXT REV HERE