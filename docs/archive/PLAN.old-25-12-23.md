# Darkstar Energy Manager: Master Plan

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

## Active Revisions

(Kepler revisions K1-K15 archived to CHANGELOG.md)

### [DONE] Rev H1 — Execution History Migration

**Goal:** Migrate execution history from MariaDB to Internal Executor's SQLite storage for standalone operation.

**Problem:** Schedule chart uses MariaDB `execution_history` table, but Internal Executor stores history in SQLite `execution_log`. Result: historical executed actions don't show up.

**Solution:**
1. Add `get_todays_slots()` method to `ExecutionHistory` class
2. Update `/api/schedule/today_with_history` to use SQLite first
3. Update `get_preserved_slots()` to try SQLite before MariaDB

**Status:** Done.

---

### [DONE] Rev F1 — Chart Display & Battery Cost Fixes

**Goal:** Fix chart display regressions from Rev H1 and implement dynamic battery cost calculation.

---

#### Issue 1: SoC Actual on Future Slots (Regression from H1)

**Bug:** `webapp.py:641` maps `soc_target_percent` → `actual_soc`. Also `history.py:get_todays_slots()` queries but doesn't return `before_soc_percent`.

**Fix:**
1. `history.py`: Add `before_soc_percent` to returned slot dict
2. `webapp.py`: Change to `slot.get("before_soc_percent")`

---

#### Issue 2: Export Not Affecting SoC Projection (Pre-existing)

**Bug:** `adapter.py` sets `battery_discharge_kw`, but `simulation.py` reads `discharge_kw`.

**Fix:** Add `"discharge_kw": discharge_kw` alias in `adapter.py`

---

#### Issue 3: Dynamic Battery Cost Calculator

**Problem:** Battery cost is static 0.02 SEK/kWh in config. No dynamic calculation exists in Darkstar — was done externally by n8n → MariaDB.

**Algorithm (weighted average):**
- Grid charge: `cost = (old_kwh * old_cost + charge_kwh * price) / new_kwh`
- PV charge (free): `cost = (old_kwh * old_cost) / (old_kwh + pv_surplus)` (dilutes cost)

**Implementation:**
1. Create `backend/battery_cost.py` with calculation logic
2. Store `battery_avg_cost_sek_kwh` in SQLite
3. Executor updates cost on each slot execution
4. Kepler reads current cost for export decisions
5. **Default: 1.0 SEK/kWh** until sufficient data

---

#### Issue 4: Price Gaps in Chart (Hours 10-13)

**Root Cause:** Historical slots in `schedule.json` have `import_price_sek_kwh: None` because they were preserved before prices were attached. The API price overlay (line 800) attempts to fix this from Nordpool, but fails.

**Analysis:**
- `schedule_map` key: naive datetime from ISO string `2025-12-21T10:00:00+01:00` → `datetime(2025, 12, 21, 10, 0)`
- `price_map` key: naive datetime from Nordpool `start` field → should match
- Issue: Either Nordpool API not returning past hours, or minute-level mismatch (schedule=15-min, Nordpool=hourly)

**Production Fix:**

1. **[MODIFY] `webapp.py:schedule_today_with_history()`**: Add debug logging to trace price_map vs schedule_map key matching

2. **[MODIFY] `webapp.py:800-802`**: Normalize keys for lookup - round to nearest resolution boundary:
```python
# Before: price = price_map.get(local_start)
# After: fuzzy match for hourly prices covering 15-min slots
price_key = local_start.replace(minute=(local_start.minute // 15) * 15, second=0, microsecond=0)
price = price_map.get(price_key)
# Fallback: try exact hour for hourly prices
if price is None:
    hour_key = local_start.replace(minute=0, second=0, microsecond=0)
    price = price_map.get(hour_key)
```

3. **[MODIFY] `db_writer.py:get_preserved_slots()`**: Ensure preserved slots always include prices from Nordpool at save time

**Status:** Planning.

---

### [IN PROGRESS] Rev O1 — Onboarding & System Profiles

**Goal:** Make Darkstar production-ready for both standalone Docker AND HA Add-on deployments with minimal user friction.

**Design Principles:**
1. **Settings Tab = Single Source of Truth** (works for both deployment modes)
2. **HA Add-on = Bootstrap Helper** (auto-detects where possible, entity dropdowns for sensors)
3. **System Profiles** via 3 toggles: Solar, Battery, Water Heater

---

#### Phase 1: HA Add-on Bootstrap

**Auto-detection:**
- `SUPERVISOR_TOKEN` available as env var (no user token needed!)
- HA URL is always `http://supervisor/core`
- Entity selectors in Add-on UI for sensor IDs (native HA dropdowns)

**Changes:**
- Update `hassio/config.yaml`: Add `homeassistant_api: true`, entity selectors for sensors
- Update `hassio/run.sh`: Auto-generate `secrets.yaml` from SUPERVISOR_TOKEN, apply entity selections to config

---

#### Phase 2: Settings Tab — Setup Section

**New "Home Assistant Connection" section in Settings → System:**
- HA URL field (read-only in Add-on mode)
- Token field (read-only in Add-on mode)
- "Test Connection" button

**New "Core Sensors" section:**
- Battery SoC sensor
- PV Production sensor
- Load Consumption sensor

---

#### Phase 3: System Profile Toggles

**Add to `config.default.yaml` → `system:`:**
```yaml
system:
  has_solar: true       # Enable PV forecasting & solar-related features
  has_battery: true     # Enable battery control & arbitrage
  has_water_heater: true # Enable water heating optimization
```

**Add to Settings → System:**
- 3 toggle switches with helper text
- Toggles hide/show relevant UI sections
- Backend skips disabled features in planner/executor

---

#### Phase 4: Validation

| Scenario | Solar | Battery | Water | Expected |
|----------|-------|---------|-------|----------|
| Full system | ✓ | ✓ | ✓ | All features |
| Battery only | ✗ | ✓ | ✗ | Grid arbitrage only |
| Solar + Water | ✓ | ✗ | ✓ | Cheap heating, no battery |
| Water only | ✗ | ✗ | ✓ | Cheapest price heating |

**Status:** Planning.

---

### [IN PROGRESS] Rev UI1 — Dashboard Quick Actions Redesign

**Goal:** Redesign the Dashboard Quick Actions for the native executor, with optional external executor fallback in Settings.

**Changes:**

#### Phase 1: New Quick Actions (4 Buttons)

1. **Run Planner** — Runs planner + immediate slot execution
   - 3-phase text: "Planning..." → "Executing..." → "Done ✓"
   
2. **Executor Toggle** (Pause/Resume)
   - Pause: Sets idle mode (zero export, min_soc, stop heating)
   - Visual: Red/orange pulsing glow when paused
   - 30-min reminder notification with "ACTIVATE" webhook action
   
3. **Toggle Vacation** — Inline arrows for duration selection
   - Options: 3, 7, 14, 21, 28 days
   - Visual: Amber glow when active, shows end date
   - Auto-disables when end date reached
   
4. **Boost Water** — Inline arrows for duration selection
   - Options: 30min, 1h, 2h (heats to 65°C)
   - Visual: Countdown timer, red glow when active

#### Phase 2: Settings Integration

- Add "External Executor Mode" toggle in Settings → Advanced
- When enabled, show "DB Sync" card with Load/Push buttons

#### Phase 3: Cleanup

- Hide Planning tab from navigation (legacy, unused since Kepler)
- Remove "Reset Optimal" button

**Status:** Planning.

---

### [IN PROGRESS] Rev UI2 — Premium Polish

**Goal:** Elevate the "Command Center" feel with live visual feedback and semantic clarity.

**Changes:**
1. **Executor Sparklines**: Live 10s-buffer charts for SoC, PV, Load.
2. **Aurora Icons**: Semantic icons (Zap, Shield, etc.) in Activity Log.
3. **Dashboard Visuals**: Grouping of Today's Stats into Grid vs Energy.
4. **Sidebar Status**: Connectivity pulse dot.

**Status:** Planning.

---

### [IN PROGRESS] Rev E1 — Native Executor

**Goal:** Replace n8n "Helios Executor" workflow with a native Python executor, enabling 100% MariaDB-free operation, full execution transparency, and end-user configurability.

**Scope:**

#### ✅ Phase 1: Core Executor (Completed)
- `executor/` package with `engine.py`, `controller.py`, `override.py`, `actions.py`, `history.py`
- 5-minute tick loop with slot plan reading
- Override logic (low SoC protection, excess PV utilization)
- HA service calls via REST API

#### ✅ Phase 2: Database & History (Completed)
- `execution_log` table in SQLite with full action details
- History API endpoints (`/api/executor/status`, `/api/executor/history`, `/api/executor/stats`)
- Auto-start on Flask startup when enabled

#### ✅ Phase 3: Config & Notifications (Completed)
- Full executor config section in `config.yaml`
- Notification toggles per action type
- Notification settings modal in UI with test button
- Correct notification format matching n8n

#### ✅ Phase 4: Frontend Tab (Completed)
- Executor tab with status hero card, 7-day stats, execution history
- Aurora-style UI with gradient hero, circular icon with glow
- Live System card with real-time HA values (SoC, PV, load, grid)
- Next slot preview as dashed entry in history
- Manual "Run Now" button

#### ✅ Phase 5: UI Entity Configuration & Quick Actions (Completed)
- **Entity Config Modal**: Edit all executor entity IDs in UI (inverter, water heater, SoC target)
- **PUT /api/executor/config** endpoint to save entity config (preserves YAML comments)
- **Quick Action Buttons**: One-tap manual overrides with duration selection (15/30/60 min)
  - Force Charge: Grid charging ON, Zero Export mode, SoC target 100%
  - Force Export: Export First mode, max discharge current
  - Force Heat: Water heater boost temperature
  - Stop All: Disable all charging/exporting/heating
- **Expandable History Rows**: Click to see planned vs commanded values + Idle badge
- **Deadlock fix**: Resolved threading issue in executor status API

#### ✅ Phase 5b: Safety & Resilience (Completed)
- **Planner Safety Check**: Abort planning if configured SoC sensor is unreachable (no more 50% fallback)
- **Discord Fallback Notifications**: `backend/notify.py` with HA-first → Discord webhook fallback chain
- **Error Persistence**: Critical errors written to `schedule.json` meta (`last_error`, `last_error_at`)
- **Dashboard Error Banner**: Red alert banner on Dashboard when `schedule.json` has `last_error`
- **Error Auto-Clear**: `last_error` automatically cleared from `schedule.json` on successful planner run

#### ✅ Phase 6: Testing & Validation (Completed)
- **111 unit tests** across 5 test files:
  - `test_executor_override.py` (27) — override evaluation logic
  - `test_executor_controller.py` (27) — controller decisions
  - `test_executor_actions.py` (20) — HAClient/ActionDispatcher with mocked HA
  - `test_executor_engine.py` (21) — engine integration with mock schedule/HA
  - `test_executor_history.py` (16) — SQLite history storage

#### ✅ Phase 6b: Legacy Code Cleanup (Completed)
- **29,865 lines deleted** across 67 files
- Deleted: `planner_legacy.py` (150KB), `archive/`, `reference/`, `docs/old/`, `Helios Executor.json`
- Removed 19 obsolete debug scripts and 11 legacy test files
- Migrated `ml/simulation/env.py` and `bin/run_simulation.py` to use `PlannerPipeline`
- All 169 remaining tests pass

#### ✅ Phase 7: Deployment (Completed)
- ✅ Secrets migration: Discord webhook moved to `secrets.yaml`
- ✅ `Dockerfile` with multi-stage build (frontend + Python)
- ✅ `docker-compose.yml` for easy local deployment
- ✅ `hassio/` Home Assistant Add-on structure
- ✅ `.dockerignore` to exclude dev files
- ✅ Clean `secrets.example.yaml` (no real credentials)
- ✅ User-focused `README.md` at root, `docs/README.md` → `docs/DEVELOPER.md`
- ✅ Verified Docker build locally
- ✅ Multi-process entrypoint (Flask API + Scheduler + Recorder)
- ✅ Config save preserves structure (ruamel.yaml)

**Status:** Complete. Released as v2.1.0.

---

### ✅ Rev K16 — Target SoC Redesign (Fixed Base Buffers)

**Goal:** Redesign the Target SoC calculation to use FIXED base buffers per risk level instead of scaling-based approach.

**Changes:**
- FIXED base buffers per risk level (+35%/+20%/+10%/+3%/-7%)
- Weather/PV deficit adjustment (±8%) independent of risk level
- Guarantees: Level 1 > Level 2 > Level 3 > Level 4 > Level 5 (ALWAYS)
- Removed duplicate `calculate_dynamic_target_soc` function in `terminal_value.py`
- Deprecated `soc_scaling_factor` config parameter

**Status:** Complete. Included in v2.1.0.

---

### ✅ Rev K17 — Water Heating as Deferrable Load

**Goal:** Move water heating from heuristic to Kepler MILP for optimal source selection.

**Approach:** Deferrable load constraint in MILP
- Add `water_heat[t]` binary variable
- Kepler decides: grid or battery (including wear cost)
- Same config params, new `max_hours_between_heating: 8`

**Changes:**
1. `types.py` — Add water heating config to `KeplerConfig`
2. `kepler.py` — Add `water_heat` variable, constraints, energy balance
3. `pipeline.py` — Skip old heuristic when Kepler water heating enabled
4. `adapter.py` — Wire up config adapter with water heating params
5. `config.default.yaml` — Add `max_hours_between_heating`

**MILP Constraints:**
- `water_heat[t] ∈ {0,1}` — Binary heating decision per slot
- Total minimum: `sum(water_heat[t] * kwh_per_slot) >= min_kwh_per_day`
- Max gap: Every 8h window must have at least one heating slot

**Status:** Complete.

---

### ✅ Rev K18 — Comfort Level & Soft Gap Constraint

**Goal:** Fix over-heating and add comfort slider for soft gap penalty.

**Problems Solved:**
1. **Over-heating:** Kepler didn't know what was already heated today
2. **Hard gap constraint:** Forces mid-day heating even when expensive

**Approach:**
- Pass `water_heated_today` to Kepler → reduce remaining min_kwh
- Replace hard gap with **soft gap penalty**
- Add `comfort_level: 1-5` slider → maps to penalty strength

**Comfort Level Mapping:**
| Level | Penalty (SEK/hour) | Behavior |
|-------|-------------------|----------|
| 1 | 0.05 | Economy |
| 3 | 0.50 | Neutral |
| 5 | 3.00 | Maximum |

**Status:** Complete.

---

### ✅ Rev K19 — Vacation Mode Anti-Legionella

**Goal:** When vacation mode is ON, disable normal comfort-based water heating and run periodic anti-legionella cycles.

**Background:**
- Legionella bacteria grow in stagnant water between 20-45°C
- Swedish regulation recommends heating to 65°C periodically to kill bacteria
- During vacation, normal heating is wasteful but safety heating is required

---

**Behavior:**

| Mode | Normal Heating | Anti-Legionella | Trigger |
|------|---------------|-----------------|---------|
| Vacation OFF | ✅ Comfort-based (K17/K18) | ❌ Not used | — |
| Vacation ON | ❌ Disabled | ✅ 3h block weekly | 6+ days since last |

**Anti-Legionella Cycle:**
- Duration: 3 hours at 3kW = 9 kWh (heats tank to 65°C)
- Frequency: Once per 7 days (check after 6 days to allow scheduling)
- Scheduling: Uses existing `max_blocks_per_day` config (can split if needed)
- Price optimization: Pick cheapest slots from available 36h window

**Price Window Constraint:**
- Tomorrow's prices arrive after 13:15
- Only trigger scheduling after 14:00 to have full price data
- Logic: `if now.hour >= 14 AND days_since_last >= 6 → schedule in next 24h`

---

**Config Changes:**

File: `config.default.yaml`
```yaml
water_heating:
  # ... existing config ...
  vacation_mode:
    enabled: false                    # Master switch
    anti_legionella_temp_c: 65        # Target temperature
    anti_legionella_interval_days: 7  # Cycle every N days
    anti_legionella_duration_hours: 3.0  # 3h at power_kw
```

---

**State Tracking (SQLite DB):**

Uses existing `learning.sqlite_path` database. Create table on first use:

```sql
CREATE TABLE IF NOT EXISTS vacation_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
```

Store: `key='last_anti_legionella_at'`, `value='2024-12-20T04:00:00+01:00'`

- Read on planner startup
- Write after anti-legionella heating is scheduled
- If missing, assume heating is due immediately

---

**Implementation Steps:**

**Step 1: Config** (`config.default.yaml`)
- Add `vacation_mode` section under `water_heating`
- Copy to user's `config.yaml`

**Step 2: DB Helper Functions** (new file `planner/vacation_state.py`)
```python
import sqlite3
from datetime import datetime
from typing import Optional

def get_db_path() -> str:
    """Get SQLite path from config"""
    # Use learning.sqlite_path from config
    return config.get("learning", {}).get("sqlite_path", "learning.db")

def load_last_anti_legionella() -> Optional[datetime]:
    """Load last anti-legionella timestamp from SQLite DB"""
    conn = sqlite3.connect(get_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vacation_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        )
    """)
    cursor = conn.execute(
        "SELECT value FROM vacation_state WHERE key = 'last_anti_legionella_at'"
    )
    row = cursor.fetchone()
    conn.close()
    return datetime.fromisoformat(row[0]) if row else None

def save_last_anti_legionella(timestamp: datetime):
    """Save timestamp to SQLite DB"""
    conn = sqlite3.connect(get_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vacation_state (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        INSERT OR REPLACE INTO vacation_state (key, value, updated_at)
        VALUES ('last_anti_legionella_at', ?, ?)
    """, (timestamp.isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()
```

**Step 3: Pipeline Logic** (`planner/pipeline.py`)
```python
from planner.vacation_state import load_last_anti_legionella, save_last_anti_legionella

# After loading config, before Kepler:
vacation_cfg = water_cfg.get("vacation_mode", {})
vacation_enabled = vacation_cfg.get("enabled", False)

if vacation_enabled:
    # Skip normal comfort heating
    kepler_config.water_heating_min_kwh = 0.0
    kepler_config.water_comfort_penalty_sek = 0.0
    
    # Check if anti-legionella is due
    last_al = load_last_anti_legionella()
    days_since = (now - last_al).days if last_al else 999
    
    if days_since >= 6 and now.hour >= 14:
        # Schedule anti-legionella: 3h block in cheapest slots
        al_kwh = vacation_cfg.get("anti_legionella_duration_hours", 3.0) * power_kw
        kepler_config.water_heating_min_kwh = al_kwh
        # After Kepler returns, save timestamp
        save_last_anti_legionella(now)
```

**Step 4: Dashboard UI** (`frontend/src/pages/Dashboard.tsx`)
- Add vacation mode toggle to Water Heater card
- Shows "Vacation Mode" badge when enabled
- API: `Api.configSave({ water_heating: { vacation_mode: { enabled: true } } })`

---

**Testing:**
1. Enable vacation mode in config
2. Manually insert old timestamp in DB: `INSERT INTO vacation_state VALUES ('last_anti_legionella_at', '2024-12-13T04:00:00', '...')`
3. Run planner after 14:00
4. Verify 3h water heating block scheduled in cheapest slots
5. Verify timestamp updated in vacation_state table

**Status:** Complete.

---

### [DONE] Rev F2 — Wear Cost Config Fix (2025-12-22)

**Goal:** Fix Kepler to use correct battery wear/degradation cost.

**Problem:** Kepler read wear cost from wrong config key (`learning.default_battery_cost_sek_per_kwh` = 0.0) instead of `battery_economics.battery_cycle_cost_kwh` (0.2 SEK).

**Solution:**
1. Fixed `adapter.py` to read from correct config key
2. Added `ramping_cost_sek_per_kw: 0.05` to reduce sawtooth switching
3. Fixed adapter to read from kepler config section

**Status:** Complete. Commits `4fdf594`, `864cce1`.

---

### [IN PROGRESS] Rev K20 — Stored Energy Cost for Discharge (2025-12-22)

**Goal:** Make Kepler consider stored energy cost in discharge decisions.

**Problem:** Kepler doesn't know what energy in the battery "cost" to store. May discharge at a loss.

**Approach:**
1. Add `stored_energy_cost_sek_per_kwh` to `KeplerConfig`
2. Read from `BatteryCostTracker` in adapter
3. Add `discharge[t] * stored_cost` to MILP objective

**Status:** Planning.

---

### [IN PROGRESS] Rev K21 — Water Heating Slot Investigation (2025-12-22)

**Goal:** Fix water heating not scheduled in cheapest slots.

**Problem:** Water heating at 01:15 (1.44 SEK) instead of 04:00+ (1.36 SEK).

---

**Investigation Findings:**

The gap constraint (`max_hours_between_heating: 8`) combined with comfort penalty (`comfort_level: 3` → 0.50 SEK/violation) is likely forcing early heating.

**Math:**
- Price difference: 1.44 - 1.36 = **0.08 SEK**
- Comfort penalty: **0.50 SEK** per gap window violation

Since 0.50 > 0.08, Kepler prefers to heat early (saving 0.50 SEK gap penalty) even though it costs 0.08 SEK more.

**Possible Fixes:**
1. **Lower comfort_level to 1** → 0.05 SEK penalty (user config change)
2. **Increase max_hours_between_heating to 12+** (more flexibility)
3. **Bug in gap constraint logic?** - Need to verify if constraint is too aggressive

---

**Decision needed:** Is this by design (comfort > price) or a bug?

**Status:** Investigation complete, awaiting user decision.

---

### [TODO] Rev K22 — Plan Cost Not Stored (2025-12-22)

**Goal:** Fix missing `planned_cost_sek` in Aurora "Cost Reality" card.

**Bug:** `slot_plans.planned_cost_sek` is always 0.0 - cost never calculated/stored.

**Impact:** Aurora tab shows no "Plan" cost, only "Real" cost.

**Status:** Investigation pending. User reports this worked 2 days ago - likely a regression.

---

### [TODO] Rev K23 — SoC Target Holding Behavior (2025-12-22)

**Goal:** Investigate why battery holds at soc_target instead of using battery freely.

**Observation:** At 22:00, battery at 33% SoC, grid 1.82 SEK. Battery should discharge but holds because soc_target=33%.

**Expected:** Battery should be used freely during day, only end at target SoC at end of horizon.

**Status:** Investigation pending.

---

### [IN PROGRESS] Rev K24 — Battery Cost Separation (Gold Standard)

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

---

## Backlog

### ⏸️ On Hold

### Rev 63 — Export What-If Simulator (Lab Prototype)
*   **Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.
*   **Status:** On Hold (Prototype exists but parked for Kepler pivot).


### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
### Rev A27 — ML Training Scheduler (Catch-Up Logic)

**Goal:** Implement a robust "Catch-Up" scheduler for ML model retraining.
*   **Catch-Up Logic:** Instead of exact time matching, check if the last successful run is older than the most recent scheduled slot.
*   **Config:** Flexible `run_days` and `run_time` in `config.yaml`.
*   **Status:** In Progress.

### [Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

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
*   **[Core] HA Entity Config Consolidation**: Currently vacation mode, learning, and other features read HA entity state at runtime. Consider consolidating all HA-derived toggles into `config.yaml` with a single source of truth pattern (config file vs. HA entity override).

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
