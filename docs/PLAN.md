# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

(Kepler revisions K1-K15 archived to CHANGELOG.md)

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

#### 🔄 Phase 7: Deployment (In Progress)
- ✅ Secrets migration: Discord webhook moved to `secrets.yaml`
- ✅ `Dockerfile` with multi-stage build (frontend + Python)
- ✅ `docker-compose.yml` for easy local deployment
- ✅ `hassio/` Home Assistant Add-on structure
- ✅ `.dockerignore` to exclude dev files
- ✅ Clean `secrets.example.yaml` (no real credentials)
- 🔲 README.md rewrite for public repo
- 🔲 Test Docker build on RPi

**Status:** In Progress (Phase 7: Docker/HA Add-on structure complete, pending README and testing).

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

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
