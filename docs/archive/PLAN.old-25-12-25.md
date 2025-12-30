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

### [DONE] Rev K21 — Water Heating Slot Investigation

Goal: Fix water heating not scheduled in cheapest slots.

Problem: Water heating at 01:15 (1.44 SEK) instead of 04:00+ (1.36 SEK).

Investigation: The gap constraint (max_hours_between_heating: 8) combined with comfort penalty (comfort_level: 3 → 0.50 SEK/violation) was forcing early heating.

Outcome: Confirmed constraint was too aggressive.

### [DONE] Rev F2 — Wear Cost Config Fix

Goal: Fix Kepler to use correct battery wear/degradation cost.

Problem: Kepler read wear cost from wrong config key (learning.default_battery_cost_sek_per_kwh = 0.0) instead of battery_economics.battery_cycle_cost_kwh (0.2 SEK).

Solution:

1.  Fixed `adapter.py` to read from correct config key.
    
2.  Added `ramping_cost_sek_per_kw: 0.05` to reduce sawtooth switching.
    
3.  Fixed adapter to read from kepler config section.

### [IN PROGRESS] Rev O1 — Onboarding & System Profiles

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

-   [ ] **HA Connection:** Add section in Settings → System with HA URL/Token fields (read-only in Add-on mode) and "Test Connection" button.
    
-   [ ] **Core Sensors:** Add selectors for Battery SoC, PV Production, Load Consumption.
    

**Phase 3: System Profile Toggles**

-   [ ] **Config:** Add `system: { has_solar: true, has_battery: true, has_water_heater: true }` to `config.default.yaml`.
    
-   [ ] **UI:** Add 3 toggle switches in Settings → System.
    
-   [ ] **Logic:** Backend skips disabled features in planner/executor.
    

Phase 4: Validation

| Scenario | Solar | Battery | Water | Expected |

|---|---|---|---|---|

| Full system | ✓ | ✓ | ✓ | All features |

| Battery only | ✗ | ✓ | ✗ | Grid arbitrage only |

| Solar + Water | ✓ | ✗ | ✓ | Cheap heating, no battery |

| Water only | ✗ | ✗ | ✓ | Cheapest price heating |

### [DONE] Rev UI1 — Dashboard Quick Actions Redesign

**Goal:** Redesign the Dashboard Quick Actions for the native executor, with optional external executor fallback in Settings.

**Phase 1: New Quick Actions (4 Buttons)**

1.  **Run Planner:** Runs planner + immediate slot execution.
2.  **Executor Toggle:** Pause/Resume (Red/orange pulsing glow when paused).
3.  **Toggle Vacation:** Inline arrows for duration selection (3, 7, 14, 21, 28 days).
4.  **Boost Water:** Inline arrows for duration selection (30min, 1h, 2h).

**Phase 2: Settings Integration**

-   [x] Add "External Executor Mode" toggle in Settings → Advanced.
-   [x] When enabled, show "DB Sync" card with Load/Push buttons.
    
**Phase 3: Cleanup**

-   [x] Hide Planning tab from navigation (legacy).
-   [x] Remove "Reset Optimal" button.
    

### [PLANNED] Rev UI2 — Premium Polish

Goal: Elevate the "Command Center" feel with live visual feedback and semantic clarity.

Changes:

1.  **Executor Sparklines:** Live 10s-buffer charts for SoC, PV, Load.
2.  **Aurora Icons:** Semantic icons (Zap, Shield, etc.) in Activity Log.
3.  **Dashboard Visuals:** Grouping of Today's Stats into Grid vs Energy.
4.  **Sidebar Status:** Connectivity pulse dot.
    

### [TODO] Rev K22 — Plan Cost Not Stored

Goal: Fix missing planned_cost_sek in Aurora "Cost Reality" card.

Bug: slot_plans.planned_cost_sek is always 0.0 - cost never calculated/stored.

Impact: Aurora tab shows no "Plan" cost, only "Real" cost.

### [TODO] Rev K23 — SoC Target Holding Behavior (2025-12-22)

**Goal:** Investigate why battery holds at soc_target instead of using battery freely.

**Observation:** At 22:00, battery at 33% SoC, grid 1.82 SEK. Battery should discharge but holds because soc_target=33%.

**Expected:** Battery should be used freely during day, only end at target SoC at end of horizon.

**Status:** Investigation pending.

**User thoughts:** Could this be due to REV 20? So might be fixed in rev 24!

### [PLANNED] Rev K24 — Battery Cost Separation (Gold Standard)

**Goal:** Eliminate Sunk Cost Fallacy by strictly separating Accounting (Reporting) from Trading (Optimization).

**Architecture:**

1.  **The Accountant (Reporting Layer):**
    * **Component:** `backend/battery_cost.py`
    * **Responsibility:** Track the Weighted Average Cost (WAC) of energy currently in the battery.
    * **Usage:** Strictly for UI/Dashboard (e.g., "Current Battery Value") and historical analysis.
    * **Logic:** `New_WAC = ((Old_kWh * Old_WAC) + (Charge_kWh * Buy_Price)) / New_Total_kWh`

2.  **The Trader (Optimization Layer):**
    * **Component:** `planner/solver/kepler.py` & `planner/solver/adapter.py`
    * **Responsibility:** Determine optimal charge/discharge schedule.
    * **Constraint:** Must **IGNORE** historical WAC.
    * **Drivers:**
        * **Opportunity Cost:** Future Price vs. Current Price.
        * **Wear Cost:** Fixed cost per cycle (from config) to prevent over-cycling.
        * **Terminal Value:** Estimated future utility of energy remaining at end of horizon (based on future prices, NOT past cost).

**Implementation Tasks:**
* [ ] **Refactor `planner/solver/adapter.py`:**
    * Remove import of `BatteryCostTracker`.
    * Remove logic that floors `terminal_value` using `stored_energy_cost`.
    * Ensure `terminal_value` is calculated solely based on future price statistics (min/avg of forecast prices).
* [ ] **Verify `planner/solver/kepler.py`:** Ensure no residual references to stored cost exist.

### NEXT REV HERE