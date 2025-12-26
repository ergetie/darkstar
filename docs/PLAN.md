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

### [IN PROGRESS] Rev UI1 — Dashboard Quick Actions Redesign

**Goal:** Redesign the Dashboard Quick Actions for the native executor, with optional external executor fallback in Settings.

**Phase 1: New Quick Actions (4 Buttons)**

1.  **Run Planner:** Runs planner + immediate slot execution.
2.  **Executor Toggle:** Pause/Resume (Red/orange pulsing glow when paused).
3.  **Toggle Vacation:** Inline arrows for duration selection (3, 7, 14, 21, 28 days).
4.  **Boost Water:** Inline arrows for duration selection (30min, 1h, 2h).

**Phase 2: Settings Integration**

-   [ ] Add "External Executor Mode" toggle in Settings → Advanced.
-   [ ] When enabled, show "DB Sync" card with Load/Push buttons.
    
**Phase 3: Cleanup**

-   [x] Hide Planning tab from navigation (legacy).
-   [x] Remove "Reset Optimal" button.
    

### [PLANNED] Rev UI2 — Premium Polish

Goal: Elevate the "Command Center" feel with live visual feedback and semantic clarity.

**Investigation Status (2025-12-25):** most features are **NOT** implemented.

**Missing Features:**

* [ ] **Executor Sparklines:** `Executor.tsx` uses static `Kpi` cards. Needs `recharts` or `react-sparklines` implementation.

* [ ] **Aurora Icons:** `ActivityLog.tsx` has `Zap` but missing `Shield` and other semantic types.

* [ ] **Dashboard Visuals:** `Dashboard.tsx` has a flat `KPIStrip`. Needs visual separation/grouping for "Grid" vs "Energy".

* [ ] **Sidebar Status:** `Sidebar.tsx` lacks the connectivity pulse dot.

! NEEDS INVESTIGATIONS IF IMPLEMENTED !

### [IN PROGRESS] Rev K21 — Water Heating Spacing & Tuning

**Goal:** Fix inefficient water heating schedules (redundant heating & expensive slots).

**Problem:**
1.  **Expensive Slots:** Heating at 01:15 (1.44 SEK) vs 04:00 (1.36 SEK) due to aggressive gap constraints/comfort penalties.
2.  **Redundant Heating:** Heating at 23:00 (Today) and 01:00 (Tomorrow) - tank is likely full, second heat is waste.

**Proposed Solution:**
1.  **Implement "Soft Efficiency Penalty" (Spacing):**
    * Add `min_spacing_hours` (default 5h) to config.
    * Add `spacing_penalty_sek` (default 0.20 SEK).
    * **Logic:** `If (Time - Last_Heat) < 5h`, add 0.20 SEK to cost.
    * **Why:** Prevents heating for small gains but allows heating for massive gains (negative prices).
2.  **Implement "Rubber Band" Gap (Top-Up):**
    * Replace strict cliff with **Progressive Discomfort Cost**.
    * **Logic:** `If Gap > Target_Gap (10h): Cost += (Excess_Hours * 0.05 SEK)`.
    * **Why:** Allows extending the gap beyond the target if significant price savings exist (e.g., waiting 2 more hours to save 0.50 SEK).
    * **Config:** Update `config.default.yaml` with `target_gap_hours` and `discomfort_cost_per_hour` (replacing or deprecating `max_hours_between_heating` strictness).

**Status:** Investigation complete, ready for implementation.

### [IN PROGRESS] Rev K22 — Plan Cost Not Stored

**Goal:** Fix missing `planned_cost_sek` in Aurora "Cost Reality" card.

**Bug:** `slot_plans.planned_cost_sek` is always 0.0 - cost never calculated/stored.

**Impact:** Aurora tab shows no "Plan" cost, only "Real" cost.

**Investigation Findings:**
* **Root Cause:** The `SlotPlan` object (in `schedule.py`) is initialized with `planned_cost_sek=0.0`, but `formatter.py` never calculates or assigns the actual value during the conversion of solver results.
* **Missing Logic:** The solver (Kepler) optimizes for total cost but the per-slot financial implication (Cash Flow) is not being reconstructed for the output schedule.

**Proposed Fix:**
1.  **Modify `planner/output/formatter.py`:**
    * Inside the slot iteration loop, calculate the net cost for the slot.
    * Formula: `(grid_import_kwh * buy_price) - (grid_export_kwh * sell_price)`.
    * Assign to `slot.planned_cost_sek`.
2.  **Definition:** Confirm if "Cost" implies strictly "Grid Bill" (Cash Flow) or "Economic Cost" (including battery wear).
    * *Decision:* Match "Real" cost in Aurora, which comes from Home Assistant's "Grid Cost". Therefore, this should be **Grid Cash Flow only**.

**Status:** Investigation complete, ready for implementation.

### [PAUSED] Rev K23 — SoC Target Holding Behavior (2025-12-22)

**Goal:** Investigate why battery holds at soc_target instead of using battery freely.

**Observation:** At 22:00, battery at 33% SoC, grid 1.82 SEK. Battery should discharge but holds because soc_target=33%.

**Expected:** Battery should be used freely during day, only end at target SoC at end of horizon.

**Investigation Findings:**
* **Root Cause:** The MILP constraint for `soc_target` is likely being applied to **all** time steps `t >= target_time`, effectively turning the target into a "floor" for the rest of the simulation.
* **Logic Check:** Standard MILP solvers often implement "target" as `SoC[t] >= Target for t in [TargetTime, End]`.
* **Fix Required:** Change the constraint to be a **point-in-time** equality or inequality: `SoC[TargetTime] >= Target`. The solver should be free to discharge *below* this level in subsequent slots if profitable (unless a new target is set).

**Status:** Investigation complete, ready for implementation.

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

### [PLANNED] Rev F3 — Water Heater Config & Control

**Goal:** Fix ignored temperature settings and add master control switch.

**Problem:**
* User changed `water_heater.temp_normal` from 60 to 40, but system still heated to 60.
* No explicit "enable/disable" toggle for water heating logic in config.

**Investigation Plan (Audit Script Required):**
* [ ] **Config Check:** Verify `config.default.yaml` for `water_heater.enabled` toggle (Likely missing).
* [ ] **Code Scan:** Check `executor/actions.py` for usage of `set_temperature`.
    * *Expectation:* `turn_on_water_heater` calls `set_operation_mode` but **ignores** `config.water_heater.temp_normal`.
* [ ] **Planner Check:** Verify `planner/scheduling/water_heating.py` does not hardcode assumptions about temperature.

**Implementation Plan:**
* [ ] **Config:** Add `water_heater.enabled: true` to `config.default.yaml`.
* [ ] **Logic:** Add `if not config.water_heater.enabled: return` to `planner/pipeline.py` (or similar).
* [ ] **Fix:** Update `executor/actions.py` to call `hass.set_temperature(entity_id, temp=config.temp_normal)` when turning on.

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