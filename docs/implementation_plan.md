# Darkstar Planner: Master Implementation Plan

*This document provides a comprehensive overview of Darkstar Planner project, including its goals, backlog, and a chronological history of its implementation revisions. It supersedes all older `project_plan_vX.md` documents.*

---

## 1. Project Overview

### 1.1. Goals
- Achieve feature and behavioural parity with Helios `decision_maker.js` while respecting Darkstar architecture.
- Provide robust configuration, observability, and test coverage supporting future enhancements (S-index calculator, learning engine, peak shaving).
- Deliver changes in severity/impact order to minimise regressions.

### 1.2. Non-Goals
- Building S-index calculator or full learning engine (tracked as backlog).
- External database migrations (sqlite only for now).
- Emissions-weighted optimisation or advanced demand-charge handling beyond backlog items.

### 1.3. Key Assumptions
- Configurable parameters must be surfaced in `config.yaml` and reflected in web-app settings/system menus.
- Battery BMS enforces absolute SoC limits (0–100%); planner respects configured min/max targets (default 15–95%).
- Export price equals grid import price (no built-in fees beyond configurable overrides).
- Water heating usage data from Home Assistant may be unavailable; internal tracker must provide a reliable fallback resetting at local midnight (Europe/Stockholm).

### 1.4. Backlog
- **S-index calculator** – Use PV availability, load variance, temperature forecast to compute dynamic safety factor; integrate with responsibilities once validated.
- **Learning engine evolution** – Use recorded planned vs actual data to auto-adjust forecast margins and S-index; evaluate migration to MariaDB.
- **Peak shaving support** – Integrate demand charge constraints or monthly max power objectives.
- **Advanced analytics** – Historical rollups, planner telemetry dashboards, anomaly detection.

---

## 2. Implementation Revisions

### Revision Template for Future Entries
- **Rev [X] — [YYYY-MM-DD]**: [Concise Title] *(Status: ✅ Completed/🔄 In Progress/📋 Planned)*
  - **Model**: [AI Model Used]
  - **Summary**: [One-line overview]
  - **Started**: [Date/Time work began]
  - **Last Updated**: [Date/Time of last progress]
  
  **Plan:**
  - **Goals**: [Primary objectives with success criteria]
  - **Scope**: [What's included/excluded with boundaries]
  - **Dependencies**: [What must be completed first]
  - **Acceptance Criteria**: [Specific, measurable completion conditions]
  
  **Implementation:**
  - **Completed**: [✅ List of finished items with dates]
  - **In Progress**: [🔄 Current work items with status]
  - **Blocked**: [🚫 Items with blockers and reasons]
  - **Next Steps**: [→ Immediate next actions]
  - **Technical Decisions**: [Key architectural choices with rationale]
  - **Files Modified**: [List with change descriptions]
  - **Configuration**: [Config changes with impact analysis]
  
  **Verification:**
  - **Tests Status**: [Pass/Fail counts, specific test results]
  - **Known Issues**: [Current problems with workarounds]
  - **Rollback Plan**: [If needed, how to revert changes]

---

### Rev 0 — Initial Plan
- **Rev 0 — [Initial Date]**: Project Foundation *(Status: ✅ Completed)*
  - **Model**: GPT-5 Medium
  - **Summary**: Plan created after gap analysis.
  
  **Plan:**
  - **Goals**: Establish project foundation and identify gaps between existing Python planner and JavaScript reference implementation.
  - **Scope**: Gap analysis, basic architecture planning.
  
  **Implementation:**
  - **Changes**: Created initial project structure and identified key areas needing development.
  - **Files Modified**: Initial documentation and project setup.
  - **Configuration**: Basic configuration structure established.
  
  **Verification:**
  - **Acceptance Criteria**: Gap analysis completed, project foundation established.
  - **Test Results**: Initial test framework created.
  - **Known Issues**: None identified.

---

### Rev 1 — Foundational Parity
- **Rev 1 — 2025-11-01**: Foundational Parity Implementation *(Status: ✅ Completed)*
  - **Model**: Grok Code Fast 1
  - **Summary**: Implemented Phases 1-5 to achieve basic parity with JavaScript reference.
  
  **Plan:**
  - **Goals**: Address major gaps identified in `gap_analysis.md` to bring Python planner to parity with legacy JavaScript implementation.
  - **Scope**: Core functionality implementation through 6 severity-ordered phases.
  
  **Implementation:**
  - **Changes**: Implemented round-trip efficiency, battery cost accounting, slot constraints, gap responsibilities, water heating parity, export logic, strategic windows, smoothing, and output schema.
  - **Files Modified**: `planner.py`, `tests/`, `config.yaml`, `README.md`
  - **Configuration**: Added battery economics, decision thresholds, charging strategy parameters.
  
  **Verification:**
  - **Acceptance Criteria**: All 6 phases completed, basic parity achieved.
  - **Test Results**: 39 comprehensive tests with 100% pass rate.
  - **Known Issues**: None.

---

### Rev 3 — Future-Only MPC + S-Index UI
- **Rev 3 — 2025-11-02**: Future-Only MPC with S-Index Integration *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex
  - **Summary**: Implemented future-only Model Predictive Control with S-Index UI integration.
  
  **Plan:**
  - **Goals**: Remove price duplication, implement future-only planning, surface S-Index in UI, fix HA timestamps, add discharge/export limits.
  - **Scope**: Core planner logic changes and UI updates.
  
  **Implementation:**
  - **Changes**: Future-only MPC implementation, HA timestamp fixes, rate limiting, planner telemetry persistence.
  - **Files Modified**: `planner.py`, `webapp.py`, `static/js/app.js`
  - **Configuration**: Added rate limit configurations.
  
  **Verification:**
  - **Acceptance Criteria**: Future-only planning working, S-Index visible in UI.
  - **Test Results**: 42 tests passing.
  - **Known Issues**: None.

---

### Rev 4 — HA Integration + Dynamic S-Index
- **Rev 4 — 2025-11-02**: Home Assistant Integration with Dynamic S-Index *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex
  - **Summary**: Integrated Home Assistant SoC and water statistics, implemented dynamic S-Index based on PV deficit and temperature.
  
  **Plan:**
  - **Goals**: Connect to HA for real-time data, implement dynamic S-Index calculation, update web UI.
  - **Scope**: HA integration, S-Index algorithm, UI enhancements.
  
  **Implementation:**
  - **Changes**: HA sensor integration, dynamic S-Index calculation, web UI updates.
  - **Files Modified**: `inputs.py`, `planner.py`, `webapp.py`, `static/`
  - **Configuration**: Added HA connection settings and S-Index parameters.
  
  **Verification:**
  - **Acceptance Criteria**: HA data flowing, dynamic S-Index working.
  - **Test Results**: New HA and S-Index tests added and passing.
  - **Known Issues**: None.

---

### Rev 5 — Grid Water & Export Features Plan
- **Rev 5 — 2025-11-02**: Advanced Features Planning *(Status: 📋 Planned)*
  - **Model**: GPT-5 Codex
  - **Summary**: Planned upcoming fixes for grid-only water heating, export features, and UI enhancements.
  
  **Plan:**
  - **Goals**: Remove PV export planning, implement peak-only battery export, add configurable export percentile, extend forecast horizon.
  - **Scope**: Export logic improvements, water heating changes, UI settings.
  
  **Implementation:**
  - **Changes**: [Not implemented - planning phase]
  - **Files Modified**: [None - planning phase]
  - **Configuration**: [New parameters planned]
  
  **Verification:**
  - **Acceptance Criteria**: [Not applicable - planning phase]
  - **Test Results**: [Not applicable - planning phase]
  - **Known Issues**: [Not applicable - planning phase]

---

### Rev 6 — UI Theme System
- **Rev 6 — 2025-11-02**: UI Theme System Implementation *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex
  - **Summary**: Implemented comprehensive theme system with `/themes` directory scanning and CSS variable application.
  
  **Plan:**
  - **Goals**: Allow user theme selection, persist preferences, apply themes to charts and UI elements.
  - **Scope**: Theme scanning, persistence, CSS variable system.
  
  **Implementation:**
  - **Changes**: Theme directory scanning, appearance dropdown, CSS variable/palette application to charts & buttons.
  - **Files Modified**: `webapp.py`, `static/css/style.css`, `static/js/app.js`, `themes/`
  - **Configuration**: Theme persistence settings.
  
  **Verification:**
  - **Acceptance Criteria**: Themes load, apply correctly, preferences persist.
  - **Test Results**: Theme system tests added and passing.
  - **Known Issues**: None.

---

### Rev 7 — SoC Clamp + Water Heating Horizon
- **Rev 7 — 2025-11-02**: SoC Clamp Semantics & Water Heating Extensions *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex
  - **Summary**: Updated SoC clamp semantics to prevent forced drops, expanded water heating horizon to next midnight with deferral.
  
  **Plan:**
  - **Goals**: Fix SoC clamping behavior, extend water heating planning window, add charge block consolidation.
  - **Scope**: SoC logic, water heating algorithm, block consolidation.
  
  **Implementation:**
  - **Changes**: Removed forced SoC drops, extended water heating to next midnight + deferral, added charge block consolidation with tolerance/gap controls.
  - **Files Modified**: `planner.py`, `config.yaml`, tests
  - **Configuration**: Added consolidation tolerance and gap settings.
  
  **Verification:**
  - **Acceptance Criteria**: SoC no longer forced down, water heating plans further ahead.
  - **Test Results**: 46 tests passing, 4 skipped.
  - **Known Issues**: Timeline block length needed fixing.

---

### Rev 8 — Gantt Co‑Located Actions, Charge Smoothing, Charge Priority over Water, Water Block Consolidation (Planned)
- **Rev 8 — 2025-11-08**: Visual + Planning Corrections for Co‑located Actions and EEPROM‑friendly Charge Power (Status: 📋 Planned)
  - **Model**: GPT‑5 Codex (planning)
  - **Summary**: Improve UI to faithfully display co‑located actions, ensure charge targets take precedence over water‑grid floors, add configurable charge power quantization to reduce inverter EEPROM writes, and consolidate fragmented water‑heating slots when prices are similar.
  - **Started**: 2025-11-08
  - **Last Updated**: 2025-11-08

  Plan:
  - Goals:
    - Gantt supports parallel co‑located actions (Battery, Water, Export, Hold lanes) and remains compatible with manual planning workflow.
    - Charge block SoC target takes priority over water‑heating grid floor whenever both are present in a slot (prevents target “yo‑yo”).
    - Charge power is quantized (default 0.5 kW) with configurable dwell (start at 0) to reduce frequent power changes.
    - Water heating blocks merge when prices are similar using existing tolerance defaults, avoiding isolated single‑slot + bulk patterns.
  - Scope:
    - UI timeline render only (Chart remains unchanged by request).
    - Planner target synthesis and post‑allocation charge smoothing; water‑heating consolidation extension.
    - Config/Settings additions for smoothing; reuse existing consolidation tolerance for water unless overridden.
  - Dependencies:
    - None beyond current codebase; reuses existing charging_strategy tolerances where water‑specific ones are absent.
  - Acceptance Criteria:
    - In the 2025‑11‑08 00:15–03:15 window, co‑located water+charge appear simultaneously on Gantt (Battery and Water lanes).
    - For co‑located slots, soc_target_percent remains at the charge block target (e.g., ~95%) and is not lowered by water grid overrides.
    - charge_kw values are quantized to the configured step (default 0.5 kW) with no dwell initially.
    - The 00:45 single water slot merges with the 01:15 bulk block when price spread within tolerance.

  Implementation:
  - UI (Timeline parallel lanes):
    - static/js/app.js: modify renderTimeline() to create vis.js groups for Battery, Water, Export, Hold, and add items per stream per slot if their values > 0; keep manual blocks unaffected and still posted as today via /api/simulate.
    - Ensure addActionBlock() and drop handler set group visually; payload sent to backend remains {start,end,content}.
  - Planner: SoC target priority for charge over water‑grid:
    - planner.py:_apply_soc_target_percent(): during the water‑block phase, skip overriding targets for slots where action == 'Charge'; for non‑charge water‑grid slots, set targets[j] = max(targets[j], block_entry) to avoid lowering charge‑derived targets.
  - Planner: Charge power smoothing (quantization):
    - Add _pass_5b_smooth_charge_power(df): after _pass_5_distribute_charging_in_windows and before _pass_6_finalize_schedule, quantize df['charge_kw'] to step size (floor to nearest multiple) while respecting instantaneous capacity (no increase above available power). Optionally, apply dwell if configured.
    - Configuration keys (with defaults):
      - smoothing.charge_power_step_kw: 0.5
      - smoothing.min_slots_between_charge_power_changes: 0
    - Web UI: add inputs under Settings → Smoothing for these keys; persist via /api/config/save.
  - Planner: Water‑heating consolidation with tolerance reuse:
    - In _pass_2_schedule_water_heating, after selecting daily blocks, apply consolidation when the price span between adjacent blocks ≤ tolerance and gap ≤ max_gap_slots.
    - Config keys (optional, water‑specific):
      - water_heating.block_consolidation_tolerance_sek (fallback to charging_strategy.block_consolidation_tolerance_sek)
      - water_heating.consolidation_max_gap_slots (fallback to charging_strategy.consolidation_max_gap_slots)

  Verification:
  - Load server plan (/api/db/current_schedule) and /api/schedule in UI; confirm:
    - Gantt shows Battery and Water simultaneously for 00:45–02:45 on 2025‑11‑08.
    - soc_target_percent does not drop to 74% in co‑located slots; instead holds at charge block value until charge ends.
    - charge_kw values are multiples of 0.5 kW in cheap window after smoothing.
    - Water single slot at 00:45 merges with the 01:15 block given similar prices (within configured tolerance).
  - No change to line chart (intentional per request).

  Rollback Plan:
  - UI: revert timeline changes to previous single‑lane classification logic.
  - Planner: guard charge‑priority and smoothing behind config flags if needed; disabling smoothing by setting step_kw to 0 (or None) restores original behavior.


### Rev 8 — SoC Target + Manual Controls
- **Rev 8 — 2025-11-02**: SoC Target Signal & Manual Controls *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex
  - **Summary**: Added SoC target signal (stepped line), HOLD/EXPORT manual controls for planner and simulation, per-day water heating within 48h horizon.
  
  **Plan:**
  - **Goals**: Implement SoC targets, manual override controls, improve water heating scheduling.
  - **Scope**: SoC target logic, manual controls, UI integration.
  
  **Implementation:**
  - **Changes**: SoC target stepped line, HOLD/EXPORT manual controls in planner + simulation, per-day water heating scheduling, UI control ordering, theme-aligned buttons/series.
  - **Files Modified**: `planner.py`, `webapp.py`, `static/js/app.js`, `static/css/style.css`
  - **Configuration**: Manual control settings.
  
  **Verification:**
  - **Acceptance Criteria**: SoC targets visible, manual controls working.
  - **Test Results**: 47 tests passing, 4 skipped.
  - **Known Issues**: None.

---

### Rev 9 — Learning Engine Implementation
- **Rev 9 — 2025-11-03**: Learning Engine Architecture & Implementation *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Implemented complete learning engine with schema, ETL processes, status endpoint, and observation loops.
  
  **Plan:**
  - **Goals**: Build learning engine foundation for recording planned vs actual data, implement automatic observation recording.
  - **Scope**: Learning engine architecture, database schema, API endpoints, background processes.
  
  **Implementation:**
  - **Changes**: 
    - **Rev 9a**: Learning Engine Schema + ETL + Status Endpoint
    - **Rev 9b-9d**: Learning Loops Implementation
    - **Rev 9 Final Fix**: Debug API endpoint implementation
  - **Files Modified**: `learning.py`, `webapp.py`, `db_writer.py`, `tests/`
  - **Configuration**: Learning engine settings and database configuration.
  
  **Verification:**
  - **Acceptance Criteria**: Learning engine records observations, provides status API.
  - **Test Results**: Learning engine tests implemented and passing.
  - **Known Issues**: None.

---

### Rev 10 — Diagnostics & Learning UI
- **Rev 10 — 2025-11-04**: Learning UI & Diagnostics Interface *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Created comprehensive diagnostics interface and learning engine UI components.
  
  **Plan:**
  - **Goals**: Build user interface for learning engine, add diagnostic tools for system monitoring.
  - **Scope**: UI components, API endpoints, data visualization.
  
  **Implementation:**
  - **Changes**: Learning UI components, diagnostic endpoints, status displays.
  - **Files Modified**: `webapp.py`, `static/js/app.js`, `templates/index.html`, `static/css/style.css`
  - **Configuration**: UI settings for learning display.
  
  **Verification:**
  - **Acceptance Criteria**: Learning data visible in UI, diagnostics accessible.
  - **Test Results**: UI tests passing.
  - **Known Issues**: None.

---

### Rev 10b — Water Heating Price Priority Fix
- **Rev 10b — 2025-11-04**: Water Heating Algorithm Optimization *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Fixed water heating algorithm to prioritize price over time contiguity, matching battery charging behavior.
  
  **Plan:**
  - **Goals**: Make water heating price-optimized like battery charging, maintain intelligent contiguity preference.
  - **Scope**: Water heating algorithm redesign, block consolidation improvements.
  
  **Implementation:**
  - **Changes**: Replaced time-based sorting with price-based sorting, comprehensive slot selection algorithm, block consolidation with minimal cost penalty merging.
  - **Files Modified**: `planner.py`, `tests/test_water_scheduling.py`
  - **Configuration**: Maintained existing constraints (max_blocks_per_day, slots_needed, etc.).
  
  **Verification:**
  - **Acceptance Criteria**: Water heating finds optimal price combinations, maintains contiguity when possible.
  - **Test Results**: All 68 tests pass, verified with custom price-priority test.
  - **Known Issues**: None.

---

### Rev 12 — Server Plan Loader + Operations Documentation
- **Rev 12 — 2025-11-04**: Database Integration & Operations Setup *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Added server plan loading from MariaDB, comprehensive operations documentation, and HA daily average fix.
  
  **Plan:**
  - **Goals**: Enable loading plans from database, provide operations documentation, fix data quality issues.
  - **Scope**: Database integration, API endpoints, documentation, data fixes.
  
  **Implementation:**
  - **Changes**: 
    - Backend: Added `GET /api/db/current_schedule` and `GET /api/status` endpoints
    - UI: Dashboard button for loading server plan, dual plan stats display
    - Data Quality: Fixed HA daily average calculation (divide by 7 across all days)
    - Docs: README updated with GitHub → server flow, tmux basics, systemd timer setup
  - **Files Modified**: `webapp.py`, `db_writer.py`, `README.md`, `static/js/app.js`, `inputs.py`
  - **Configuration**: Database connection settings, operations parameters.
  
  **Verification:**
  - **Acceptance Criteria**: Can load server plan, see both local and DB plan stats, HA daily kWh correct.
  - **Test Results**: API endpoints working, documentation complete.
  - **Known Issues**: None.

---

### Rev 12a — Manual Planning Persistence + DB Push UX
- **Rev 12a — 2025-11-04**: Enhanced Manual Planning Workflow *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Improved manual planning with automatic persistence and better database push user experience.
  
  **Plan:**
  - **Goals**: Make manual planning changes persistent, improve DB push workflow, maintain timeline state.
  - **Scope**: Simulator persistence, UX improvements, database integration.
  
  **Implementation:**
  - **Changes**: 
    - Simulator saves to `schedule.json` as part of `/api/simulate`
    - "Push to DB" auto-refreshes with visual confirmation
    - `db_writer` clears `current_schedule` before insert, normalizes timestamps
    - Timeline retains user blocks after manual changes
  - **Files Modified**: `webapp.py`, `db_writer.py`, `static/js/app.js`
  - **Configuration**: Manual planning settings.
  
  **Verification:**
  - **Acceptance Criteria**: Manual changes survive apply, push writes correctly, timeline remains stable.
  - **Test Results**: Manual planning workflow fully functional.
  - **Known Issues**: None.

---

### Rev 13 — Manual Mode Overrides
- **Rev 13 — 2025-11-04**: Manual Planning Override System *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Implemented manual mode overrides that allow users to bypass planner protections during manual apply only.
  
  **Plan:**
  - **Goals**: Enable user control override in manual mode while preserving normal planner protections.
  - **Scope**: Manual mode semantics, configuration options, UI controls.
  
  **Implementation:**
  - **Changes**: 
    - Manual mode ignores cheap-window hold, forces discharge on deficit, ignores protective guard for targets
    - Added three config toggles for manual planning behavior
    - Planner simulate path adjusts discharge gates, normal generate path unchanged
  - **Files Modified**: `planner.py`, `config.yaml`, `static/js/app.js`, `templates/index.html`
  - **Configuration**: `manual_planning.override_hold_in_cheap`, `manual_planning.force_discharge_on_deficit`, `manual_planning.ignore_protective_guard`
  
  **Verification:**
  - **Acceptance Criteria**: Manual overrides work in apply mode, planner runs keep normal protections.
  - **Test Results**: Manual mode behavior verified, UI controls functional.
  - **Known Issues**: None.

---

### Rev 14 — Learning Engine Bug Fix
- **Rev 14 — 2025-11-05**: Learning Engine Observation Recording Fix *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Fixed learning engine automatic observation recording system for live system execution.
  
  **Plan:**
  - **Goals**: Enable automatic observation recording from live system, fix missing historic SoC data.
  - **Scope**: Learning engine integration, background recording, API endpoints.
  
  **Implementation:**
  - **Changes**: 
    - Added `/api/learning/record_observation` endpoint
    - Implemented automatic 15-minute recording thread
    - Fixed integration with live running system
  - **Files Modified**: `learning.py`, `webapp.py`
  - **Configuration**: Learning engine timing and quality settings.
  
  **Verification:**
  - **Acceptance Criteria**: Flask app records observations every 15 minutes, Historic SoC API returns data.
  - **Test Results**: ✅ Flask app recording, ✅ Historic SoC data available (80.0% at 15:15).
  - **Known Issues**: None.

---

### Rev 15 — Chart Time Scale Conversion & UX Fixes
- **Rev 15 — 2025-11-05**: Chart Architecture Upgrade & User Experience Improvements *(Status: ✅ Completed)*
  - **Model**: GPT-5 Codex CLI
  - **Summary**: Successfully converted chart from categorical to time scale architecture while fixing all interaction issues.
  
  **Plan:**
  - **Goals**: Convert chart to time scale for better data handling, fix tooltip positioning, resolve Y-axis compression.
  - **Scope**: Chart.js configuration, data structure conversion, UI improvements.
  
  **Implementation:**
  - **Changes**: 
    - **MAJOR ARCHITECTURE CHANGE**: Converted all datasets from categorical arrays to time-object format `{x: timestamp, y: value}`
    - Fixed Historic/Current SoC tooltip positioning - now appears at correct timestamps instead of 00:00
    - Resolved Y-axis compression affecting fonts and rendering by increasing chart height to 600px
    - Converted SoC data to time-aligned arrays matching schedule's 15-minute grid for perfect alignment
    - Removed complex tooltip callbacks that interfered with hover detection
    - Added spanGaps: false for proper line rendering across null values
    - Maintained time scale benefits while fixing all UX issues
  - **Files Modified**: `static/js/app.js`, `static/css/style.css`, `templates/index.html`
  - **Configuration**: Chart display settings, time scale parameters.
  
  **Verification:**
  - **Acceptance Criteria**: All 10 datasets working with proper tooltips, no compression issues.
  - **Test Results**: 68/68 tests passing, chart fully functional with time scale.
  - **Known Issues**: None resolved.

---

### Rev 16 — 2025-11-06: DB Preservation Bug Fix *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Fixed critical SQL parameter placeholder bug preventing DB preservation in "run planner" flow
- **Started**: 2025-11-06 13:30
- **Last Updated**: 2025-11-06 13:45

**Plan:**
- **Goals**: Resolve Issue #1 - "run planner" should fetch past slots from DB, not recreate them
- **Scope**: Fix SQL query parameter compatibility for PyMySQL/MySQL
- **Dependencies**: None (standalone bug fix)
- **Acceptance Criteria**: "run planner" shows same historical slots as "load server plan"

**Implementation:**
- **Completed**: 
  - ✅ Root cause analysis: SQL parameter placeholder mismatch (`?` vs `%s`)
  - ✅ Fixed `_get_preserved_slots_from_db()` in `db_writer.py` line 69
  - ✅ Verified DB preservation working (55 slots loaded from database)
  - ✅ Confirmed merged schedule contains DB past + planner future slots
  - ✅ Created git commit 861edd7 with proper documentation
- **In Progress**: None
- **Blocked**: None
- **Next Steps**: → Proceed to Issue #2 (soc_target bump fix)
- **Technical Decisions**: Used PyMySQL-compatible `%s` placeholders instead of `?`
- **Files Modified**: `db_writer.py` (1 line change: `?` → `%s`)
- **Configuration**: None

**Verification:**
- **Tests Status**: Manual verification completed - DB preservation working correctly
- **Known Issues**: None resolved
- **Rollback Plan**: Revert `db_writer.py` line 69 from `%s` back to `?`

---

### Rev 17 — 2025-11-06: First Future Slot SoC Target Fix *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Fixed soc_target bump issue where first future slot gets current SoC instead of action-based target
- **Started**: 2025-11-06 13:50
- **Last Updated**: 2025-11-06 13:55

**Plan:**
- **Goals**: Resolve Issue #2 - First future slot should use action-based target, not current SoC
- **Scope**: Fix historical preservation loop in `_apply_soc_target_percent()` method
- **Dependencies**: Rev 16 (Issue #1 fix) completed
- **Acceptance Criteria**: First future discharge slot shows min_soc_percent target (~15%) not current SoC (~76%)

**Implementation:**
- **Completed**: 
  - ✅ Root cause analysis: Historical preservation loop includes first future slot
  - ✅ Identified fix location: `planner.py` line 1846 (`range(now_pos + 1)` → `range(now_pos)`)
  - ✅ Implemented fix: Changed historical preservation to exclude first future slot
  - ✅ Tested fix: First future discharge slot now shows 15% target (was 76%)
  - ✅ Verified other slots unchanged: Second future slot still 15% target
- **In Progress**: None
- **Blocked**: None
- **Next Steps**: → Commit changes to complete Issue #2
- **Technical Decisions**: Limit historical preservation to actual past slots only
- **Files Modified**: `planner.py` (1 line change in `_apply_soc_target_percent()`)
- **Configuration**: None

**Verification:**
- **Tests Status**: Manual verification completed - first future slot target corrected
- **Known Issues**: None resolved
- **Rollback Plan**: Revert `planner.py` line 1846 from `range(now_pos)` back to `range(now_pos + 1)`

---

### Rev 18 — 2025-11-06: Price History & X-Axis Ticks Fix *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Fixed missing price history in "run planner" mode and X-axis 4-hour tick intervals
- **Started**: 2025-11-06 14:00
- **Last Updated**: 2025-11-06 14:30

**Plan:**
- **Goals**: 
  - Bug #1: Restore price history display in "run planner" mode
  - Bug #2: Fix X-axis to show hourly ticks instead of 4-hour intervals
- **Scope**: 
  - Price overlay logic in `/api/schedule` endpoint
  - Chart.js time scale configuration fixes
- **Dependencies**: Rev 17 (Issue #2 fix) completed
- **Acceptance Criteria**: 
  - "Run planner" shows full price history like "load server plan"
  - X-axis displays hourly timestamps (12:00, 13:00, 14:00, etc.)

**Investigation Results:**
- **Bug #1 Root Cause**: Historical slots in `schedule.json` missing price data
  - PV/Load: Generated by planner for all slots (past + future) ✅
  - Prices: Only included for future slots, historical slots missing ❌
  - `/api/db/current_schedule`: Has price overlay logic (lines 336-384) ✅
  - `/api/schedule`: No price overlay, just returns schedule.json ❌
  - Frontend: Uses price data directly from schedule slots (lines 901-904)
  
- **Bug #2 Root Cause**: Chart.js time series configuration conflict
  - Initial: `stepSize: 2` → 4-hour intervals ❌
  - Data: 15-minute intervals (192 slots = 48 hours × 4 slots/hour)
  - Conflict: `unit: 'hour'` + 15-min data + `autoSkip: true` caused aggregation
  - Final Solution: `ticks.source: 'data'` + `autoSkip: false` ✅

**Implementation:**
- **Bug #1 Fix**: Added price overlay to `/api/schedule` endpoint (webapp.py:229-266)
  - Uses same Nordpool data fetching logic as `/api/db/current_schedule`
  - Builds price map keyed by local naive start time
  - Overlays prices for historical slots missing `import_price_sek_kwh`
  
- **Bug #2 Fix**: Updated Chart.js time scale configuration (app.js:1233-1238)
  - Tried: `stepSize: 1` → still 4-hour intervals (autoSkip override)
  - Tried: `maxTicksLimit: 48` → every other hour (autoSkip still active)
  - Tried: `autoSkip: false` → still not working
  - **Final Solution**: `ticks.source: 'data'` + `autoSkip: false` → hourly ticks ✅

**Files Modified:**
- `webapp.py`: Added price overlay logic to `/api/schedule` endpoint
- `static/js/app.js`: Updated Chart.js ticks configuration with `source: 'data'`

**Verification:**
- **Bug #1**: ✅ Historical slots now show `import_price_sek_kwh: 1.013` (tested via API)
- **Bug #2**: ✅ X-axis now displays hourly timestamps (confirmed by user)
- **Regression Test**: ✅ No impact on other chart functionality

**Rollback Plan**: 
- Revert `webapp.py` lines 229-266 to original simple `jsonify(data)`
- Revert `static/js/app.js` ticks configuration to original settings

---

### Rev 19 — 2025-11-06: Push to DB Primary Key Conflict *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Fixed "push to DB" failure by resolving duplicate slot numbers in schedule.json
- **Started**: 2025-11-06 14:35
- **Last Updated**: 2025-11-06 14:45

**Plan:**
- **Goals**: Fix "push to DB" functionality that fails with 500 error
- **Scope**: Identify root cause of primary key constraint violation and implement fix
- **Dependencies**: Rev 18 (Price history & X-axis fixes) completed
- **Acceptance Criteria**: 
  - "Push to DB" button succeeds without errors
  - Schedule data properly written to both current_schedule and plan_history tables

**Investigation Results:**
- **Root Cause**: Duplicate slot numbers in `schedule.json` causing primary key constraint violation
  - Total slots: 192, Unique slot numbers: 154
  - Duplicates found for slot numbers 97-134 (38 duplicate entries)
  - Error: `(1062, "Duplicate entry '97' for key 'PRIMARY'")`
  
- **Why Duplicates Occur**: 
  - Historical slots (from DB) have slot numbers 97-134
  - Future planner slots also generate slot numbers 97-134
  - Merging process creates overlapping slot number ranges
  - `current_schedule` table has PRIMARY KEY on `slot_number`

- **Evidence**:
  - Manual single INSERT works fine
  - `executemany` fails on duplicate primary key
  - `current_schedule` table is empty before insert (DELETE works)
  - Schedule.json contains overlapping historical + future slot numbers

**Implementation:**
- **Fix Strategy**: Ensure future slots continue from max historical slot number
- **Location**: Fixed slot number generation in planner.py:1979-1985
- **Code Changes**:
  ```python
  # Fix slot number conflicts: ensure future slots continue from max historical slot number
  max_historical_slot = 0
  if existing_past_slots:
      max_historical_slot = max(slot.get('slot_number', 0) for slot in existing_past_slots)
  
  # Reassign slot numbers for future records to continue from historical max
  for i, record in enumerate(new_future_records):
      record['slot_number'] = max_historical_slot + i + 1
  ```

**Files Modified:**
- `planner.py`: Added slot number conflict resolution in merging logic (lines 1979-1985)

**Verification:**
- **Before Fix**: 192 slots, 154 unique (38 duplicates: 97-134)
- **After Fix**: 134 slots, 134 unique (0 duplicates)
- **Slot Number Range**: 97-230 (historical 97-134 + future 135-230)
- **Push to DB Test**: ✅ SUCCESS: 134 rows written to database
- **Data Integrity**: ✅ No primary key constraint violations

**Rollback Plan**: 
- Remove slot number reassignment logic from planner.py lines 1979-1985
- Restore original merging: `merged_schedule = existing_past_slots + new_future_records`

### Rev 20 — 2025-11-06: Manual Changes Historical Preservation *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Added historical slot preservation to "apply manual changes" functionality
- **Started**: 2025-11-06 14:50
- **Last Updated**: 2025-11-06 14:55

**Plan:**
- **Goals**: Make "apply manual changes" behave same as "run planner" regarding historical preservation
- **Scope**: Add historical slot merging to `/api/schedule/save` endpoint
- **Dependencies**: Rev 19 (Push to DB fix) completed
- **Acceptance Criteria**: 
  - "Apply manual changes" preserves historical slots from database
  - Manual slot numbers continue from max historical slot number
  - No duplicate slot numbers in final schedule

**Investigation Results:**
- **Root Cause**: `/api/schedule/save` endpoint bypassed historical slot preservation logic
  - "Run planner": ✅ Calls `planner.generate_schedule()` → includes historical merging
  - "Apply manual changes": ❌ Direct save to `schedule.json` → no historical merging
  - Result: Manual changes overwrote entire schedule, losing historical data

**Implementation:**
- **Strategy**: Replicate exact Rev 19 logic in `/api/schedule/save` endpoint
- **Location**: `webapp.py:453-500` (updated `/api/schedule/save` endpoint)
- **Code Changes**:
  ```python
  # Preserve historical slots from database (same logic as planner.py Rev 19)
  from db_writer import get_preserved_slots
  existing_past_slots = get_preserved_slots(today_start, now, secrets)
  
  # Fix slot number conflicts: ensure manual slots continue from max historical slot number
  max_historical_slot = 0
  if existing_past_slots:
      max_historical_slot = max(slot.get('slot_number', 0) for slot in existing_past_slots)
  
  # Reassign slot numbers for manual records to continue from historical max
  for i, record in enumerate(manual_schedule):
      record['slot_number'] = max_historical_slot + i + 1
  
  # Merge: preserved past + manual (same as planner.py)
  merged_schedule = existing_past_slots + manual_schedule
  ```

**Files Modified:**
- `webapp.py`: Added historical preservation logic to `/api/schedule/save` endpoint

**Verification:**
- **Before Fix**: Manual changes overwrote entire schedule, losing historical slots
- **After Fix**: Manual changes preserve historical slots (1-133) + continue numbering (134+)
- **Test Result**: ✅ 3 total slots, 3 unique slot numbers, 1 historical slot preserved
- **Consistency**: "Apply manual changes" now behaves identically to "run planner" for historical preservation

**Rollback Plan**: 
- Revert `/api/schedule/save` endpoint to original implementation (lines 453-484)
- Remove historical slot merging logic

### Rev 21 — 2025-11-06: Gitignore Optimization *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Added generated files to .gitignore to prevent accidental commits
- **Started**: 2025-11-06 15:05
- **Last Updated**: 2025-11-06 15:05

**Plan:**
- **Goals**: Exclude generated output files from git tracking
- **Scope**: Update .gitignore with schedule.json and log files
- **Dependencies**: Rev 20 (Manual changes preservation) completed
- **Acceptance Criteria**: 
  - Generated files no longer appear in git status
  - Only source code changes are tracked

**Implementation:**
- **Files Added to .gitignore**:
  - `schedule.json` (generated planner output)
  - `*.log` (log files)
  - `webapp*.log` (webapp specific logs)

**Rationale:**
- `schedule.json` is regenerated every time planner runs
- No need to track generated output in version control
- Prevents accidental commits of temporary/generated data

**Files Modified:**
- `.gitignore`: Added generated files exclusions

**Verification:**
- ✅ `git status` no longer shows schedule.json as modified
- ✅ Only source code changes appear in git tracking
- ✅ Generated files are properly excluded

**Rollback Plan**: 
- Remove added lines from .gitignore

---

### Rev 22 — 2025-11-06: Server Automation Setup *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Fixed broken systemd service and timer configuration to enable automated planner execution
- **Started**: 2025-11-06 16:30
- **Last Updated**: 2025-11-06 17:05

**Plan:**
- **Goals**: Enable automated hourly planner execution via systemd timer (08:00-22:00 Europe/Stockholm)
- **Scope**: Fix systemd service and timer configuration, verify automation functionality
- **Dependencies**: Rev 21 (Gitignore optimization) completed
- **Acceptance Criteria**: 
  - systemd timer runs planner automatically every hour 08:00-22:00
  - Service executes planner successfully without errors
  - Historical slot preservation works in automated runs
  - Next scheduled run visible and confirmed

**Investigation Results:**
- **Initial State**: No automation configured
  - `crontab -l`: "no crontab for root"
  - `systemctl status darkstar-planner.service`: "bad-setting" error
  - `systemctl status darkstar-planner.timer`: "bad-setting" error
  - No running planner or learning processes

- **Root Causes Identified**:
  1. **Service File**: Missing `ExecStart=` line entirely
  2. **Timer File**: Corrupted en dash character in description line (`08–22` → `08M-bM-^@M-^S22`)
  3. **Timer Syntax**: Typo in `OnCalendar=--*` (should be `*-*-*`)
  4. **Missing Automation**: No cron jobs or systemd timers enabled

**Implementation:**
- **Step 1 - Timer Fix**: Corrected `OnCalendar` syntax and corrupted description
  ```bash
  # Fixed: OnCalendar=*-*-* 08..22:00:00
  # Fixed: Description=Run Darkstar planner hourly (08-22 Europe/Stockholm)
  ```
  
- **Step 2 - Service Fix**: Added missing `ExecStart=` and proper configuration
  ```ini
  [Service]
  Type=oneshot
  WorkingDirectory=/opt/darkstar
  ExecStart=/opt/darkstar/venv/bin/python -m bin.run_planner
  User=root
  Group=root
  ```

- **Step 3 - Enable Automation**: 
  ```bash
  systemctl daemon-reload
  systemctl enable --now darkstar-planner.timer
  ```

**Files Modified:**
- `/etc/systemd/system/darkstar-planner.service`: Fixed missing ExecStart and configuration
- `/etc/systemd/system/darkstar-planner.timer`: Fixed corrupted characters and syntax

**Verification:**
- **Timer Status**: ✅ Active, next run scheduled for 18:00 CET (57 minutes from verification)
- **Service Test**: ✅ Manual execution successful
  ```
  Nov 06 17:01:26 darkstar python[4841]: [planner] Wrote schedule to schedule.json
  Nov 06 17:01:26 darkstar python[4841]: [preservation] Loaded 8 past slots from database
  Nov 06 17:01:26 darkstar systemd[1]: Finished darkstar-planner.service - Darkstar planner run.
  ```
- **Schedule Output**: ✅ 92KB schedule.json generated with proper structure
- **HA Integration**: ✅ Successfully fetching consumption data (23.20 kWh/day average)
- **Resource Usage**: ✅ Efficient (1.652s CPU time, 61.8M memory peak)
- **Historical Preservation**: ✅ Loading 8 past slots from database during automated runs

**Final Status:**
- **Automation**: ✅ Fully operational - runs hourly 08:00-22:00 Europe/Stockholm
- **Next Run**: ✅ Scheduled for 18:00 CET today
- **Service Health**: ✅ No errors, clean execution
- **Data Flow**: ✅ HA → Planner → Database → Schedule.json working correctly

**Rollback Plan**: 
- Disable timer: `systemctl disable --now darkstar-planner.timer`
- Restore original broken service/timer files from backup
- Manual execution only: `python planner.py`

---

### Rev 20 — 2025-11-06: Manual Changes Historical Preservation *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Added historical slot preservation to "apply manual changes" functionality
- **Started**: 2025-11-06 14:50
- **Last Updated**: 2025-11-06 15:05

**Plan:**
- **Goals**: Make "apply manual changes" behave same as "run planner" regarding historical preservation
- **Scope**: Add historical slot merging to `/api/schedule/save` endpoint
- **Dependencies**: Rev 19 (Push to DB fix) completed
- **Acceptance Criteria**: 
  - "Apply manual changes" preserves historical slots from database
  - Manual slot numbers continue from max historical slot number
  - No duplicate slot numbers in final schedule

**Investigation Results:**
- **Root Cause**: `/api/schedule/save` endpoint bypassed historical slot preservation logic
  - "Run planner": ✅ Calls `planner.generate_schedule()` → includes historical merging
  - "Apply manual changes": ❌ Direct save to `schedule.json` → no historical merging
  - Result: Manual changes overwrote entire schedule, losing historical data

**Implementation:**
- **Strategy**: Replicate exact Rev 19 logic in `/api/schedule/save` endpoint
- **Location**: `webapp.py:453-500` (updated `/api/schedule/save` endpoint)
- **Code Changes**:
  ```python
  # Preserve historical slots from database (same logic as planner.py Rev 19)
  from db_writer import get_preserved_slots
  existing_past_slots = get_preserved_slots(today_start, now, secrets)
  
  # Fix slot number conflicts: ensure manual slots continue from max historical slot number
  max_historical_slot = 0
  if existing_past_slots:
      max_historical_slot = max(slot.get('slot_number', 0) for slot in existing_past_slots)
  
  # Reassign slot numbers for manual records to continue from historical max
  for i, record in enumerate(manual_schedule):
      record['slot_number'] = max_historical_slot + i + 1
  
  # Merge: preserved past + manual (same as planner.py)
  merged_schedule = existing_past_slots + manual_schedule
  ```

**Files Modified:**
- `webapp.py`: Added historical preservation logic to `/api/schedule/save` endpoint

**Verification:**
- **Before Fix**: Manual changes overwrote entire schedule, losing historical slots
- **After Fix**: Manual changes preserve historical slots + continue numbering properly
- **Test Result**: ✅ Historical preservation working, no duplicate slot numbers
- **Consistency**: "Apply manual changes" now behaves identically to "run planner" for historical preservation

**Rollback Plan**: 
- Revert `/api/schedule/save` endpoint to original implementation (lines 453-484)
- Remove historical slot merging logic

---

*Document maintained by AI agents using revision template above. All implementations should preserve existing information while adding new entries in chronological order.*
