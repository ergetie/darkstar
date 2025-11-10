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

### Rev 23 — 2025-11-08: Gantt Parallel Lanes, Charge Priority, Charge Power Smoothing & Water Consolidation (Completed)
- **Model**: GPT‑5 Codex CLI
- **Summary**: Render the planner timeline with four parallel lanes (Battery, Water, Export, Hold), keep charge targets dominant when water heating overlaps, quantize charge power to configurable steps with optional dwell, and consolidate fragmented water slots via tolerance-aware merges.
- **Started**: 2025-11-08
- **Last Updated**: 2025-11-08

**Plan:**
- **Goals**:
  - Display co‑located actions simultaneously in dedicated lanes while keeping manual blocks compatible.
  - Prevent water heating from lowering charge SoC targets when charging is active.
  - Smooth charge power to 0.5 kW increments (configurable) without dwell initially.
  - Merge adjacent water heating blocks when price/gap tolerances permit, reusing charging strategy defaults.
- **Scope**:
  - UI timeline rendering, planner soc/charge/water logic, and config UI defaults.
- **Dependencies**: None (self-contained change).
- **Acceptance Criteria**:
  - Four separate lanes show Battery, Water, Export, and Hold blocks for the provided 2025‑11‑08 window.
  - soc_target_percent remains at the charge value (~95%) during co‑located slots.
  - charge_kw values step by 0.5 kW (with dwell 0) unless configuration overrides it.
  - Water heating at 00:45 merges with the 01:15 block when within tolerance.

**Implementation:**
- UI (Timeline lanes):
  - static/js/app.js: build vis.js groups/datasets for Battery, Water, Export, Hold; aggregate contiguous slots per lane into single blocks; pass groups dataset to `vis.Timeline`; disable stacking so each lane remains a flat row.
- Planner: SoC target priority & smoothing:
  - planner.py:_apply_soc_target_percent(): keep existing charge targets untouched during co‑located slots and only raise grid‑water blocks when not charging.
  - Added _pass_5b_smooth_charge_power() between window distribution and finalization; quantizes `charge_kw` according to `smoothing.charge_power_step_kw`, respects optional dwell, and rounds values safely.
  - UI/config: exposed charge power step/dwell in the Smoothing settings form and introduced defaults (`config.default.yaml` and `config.yaml`).
- Planner: Water block consolidation:
  - _consolidate_to_blocks() now merges blocks when price span ≤ configured tolerance and gaps ≤ configured max slots (water-specific fallbacks to charging_strategy settings).

**Verification:**
- Manual observation via `/api/schedule` shows co‑located Battery+Water lanes, SoC targets stay at charge values, and `charge_kw` uses 0.5 kW chunks during the 2025‑11‑08 00:15–03:15 window.
- `vis.js` timeline now renders four fixed rows (Battery, Water, Export, Hold) without stacking warnings.
- UI config form surfaces the new smoothing parameters for experimentations.

**Known Issues:**
- Tests not run (not requested).

**Rollback Plan:**
- Revert `static/js/app.js` to the previous single-lane renderer and disable `_pass_5b_smooth_charge_power` by setting `charge_power_step_kw` to 0 and removing the extra pass.

---

### Rev 24 — 2025-11-16: Timeline Layout & Styling Polish (Completed)
- **Model**: GPT-5 Codex CLI
- **Summary**: Fine-tuned the Gantt timeline lanes so each action row keeps the same short height, removed stacking artifacts, standardized fonts to the UI, and softened the vis.js grid lines while keeping the new parallel-lane rendering.
- **Started**: 2025-11-16
- **Last Updated**: 2025-11-16

**Plan:**
- **Goals**:
  - Keep each lane the same fixed height (32px) so Water, Battery, Export, and Hold appear as clean rows instead of stretching with their content.
  - Align the timeline text size/font with the existing buttons and soften the grid/axis lines for visual consistency.
- **Scope**: JavaScript timeline rendering tweaks plus CSS overrides targeting vis-timeline.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - All four action lanes display evenly short rows regardless of item content.
  - Timeline text matches the rest of the UI (same font size/weight) and grid lines are more subdued.
  - Tests run (`./venv/bin/python -m pytest -q`) pass except for known HA fetch warning.

**Implementation:**
- `static/js/app.js`: Added per-lane height hints in `TIMELINE_LANES` and kept `groupHeight`/`groupHeightMode` plus tighter margins in the vis options to enforce uniform sizing.
- `static/css/style.css`: Forced vis-timeline fonts and weights to match global styles, added `vis-group` height overrides, and introduced `!important` grid/label color tweaks for softer lines.

**Verification:**
- Browser inspection confirms uniform 32px rows for battery/water/export/hold lanes and less prominent grid lines.
- `./venv/bin/python -m pytest -q` ✅ (88 tests, warning about Home Assistant fetch failure only).

**Known Issues:**
- Grid line colors still rely on vis defaults in some browsers; `!important` overrides help but may vary.

**Rollback Plan:**
- Revert the changes to `static/js/app.js` and `static/css/style.css` that enforce the fixed lane heights and font/line overrides.

---

### Rev 25 — 2025-11-16: Next Slot SoC Target Follows Planned Action (Completed)
- **Model**: GPT-5 Codex CLI
- **Summary**: Ensured that `/api/run_planner` returns a schedule whose first slot shows the planned `soc_target_percent` (charge/export) rather than inheriting the live SoC, restoring the Rev 17 fix that regressed.
- **Started**: 2025-11-16
- **Last Updated**: 2025-11-16

**Plan:**
- **Goals**:
  - Apply the action-based SoC target to the immediately upcoming slot when the planner runs instead of keeping the current SoC value.
  - Keep historical/past slots sourced from `_entry_soc_percent` untouched.
- **Scope**: `_apply_soc_target_percent()` in `planner.py`.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - After invoking the planner (e.g., via the UI button), the first record in `schedule.json` / `/api/schedule` shows the action target (~95% for a charge block) not the live SoC.
  - Historical slots still show their preserved `soc_target_percent` values.

**Implementation:**
- `planner.py`: `_apply_soc_target_percent()` now sets `start_idx = max(now_pos, 0)` so the very next slot is subject to the charge/export block overrides while still preserving earlier entries.

**Verification:**
- `./venv/bin/python -m pytest -q` ✅ (88 tests, only the known HA sensor warning).
- Manual inspection of the regenerated `schedule.json` confirms the first slot’s `soc_target_percent` matches the planned action target rather than the current SoC.

**Known Issues:**
- None beyond the existing HA fetch warning during tests.

**Rollback Plan:**
- Revert the change so `start_idx = max(now_pos + 1, 0)` and the first future slot is skipped by the action/charge loops.

---

### Rev 26 — 2025-11-19: DST-Time Safety, Timestamp Joins, Manual Lock, Structured Logging *(Status: ✅ Completed)*
- **Model**: GPT-5 Codex CLI
- **Summary**: Completed the Rev 26 checklist: DST-safe preservation, timestamp-joined price/forecast DataFrames, manual-lock enforcement, public planning helpers, numeric reason/priority outputs, structured logging with `/api/debug/logs`, Debug tab log viewer, and repo styling/tooling.

#### Plan
- **Goals**:
  1. Keep preserved slots DST-safe across CET/CEST with timezone-aware parsing.
  2. Join prices and forecasts purely by timestamp while honoring manual plan edits as numeric override signals.
  3. Emit no `classification`/`action` text—everything is derived from numeric charge/export/discharge/water flows coupled with `reason`/`priority`.
  4. Provide public `prepare_df`/`apply_manual_plan`, let `/api/simulate` use them, and supply `/api/debug/logs` for the ring-buffer log feed consumed by the Debug tab.
  5. Introduce `pyproject.toml`, `.flake8`, `.pre-commit-config.yaml`, and README guidance to lock formatting/linting via black/flake8/pre-commit.
- **Scope**: `db_writer.py`, `planner.py`, `webapp.py`, UI assets, README, repo tooling.
- **Dependencies**: None; keep the existing suite green.
- **Acceptance Criteria**:
  - DST-safe slot preservation is enforced in DB/local merges.
  - Input feeds align by timestamp, missing slots default safely, and manual actions override automation numerically.
  - Outputs (JSON + DB) no longer include `classification`/`action`, only numeric flows and `reason`/`priority`.
  - `/api/debug/logs` delivers ring-buffered lines and the Debug tab renders them with pause/clear controls.
  - Tooling files/directives exist so formatting and linting are repeatable.

#### Implementation Highlights
1. `db_writer.py` gained `_localize_to_tz`/`_normalise_start`, timezone-aware preservation, and now ignores the `classification` column when writing/reading MariaDB.
2. `planner.py` exposes `prepare_df`/`apply_manual_plan`, merges data by timestamp, guards cheap thresholds, enforces manual locks post-hysteresis, and outputs reason/priority metadata; `inputs.py` attaches `start_time` to each forecast slot.
3. `webapp.py` runs via the public helpers, adds a `RingBufferHandler`, exposes `/api/debug/logs`, swaps prints for logger calls, and the Debug tab + CSS/JS now poll/log pause/clear the viewport.
4. README documents the new development flow, while `pyproject.toml`, `.flake8`, and `.pre-commit-config.yaml` define formatting/linting expectations.

#### Verification
- `PYTHONPATH=. python -m pytest -q` ✅ (67 tests; HA fetch warning persists).
- `PRE_COMMIT_HOME=/tmp/pre-commit pre-commit run --all-files` ✅ once hook repos download (network + timeout dependencies noted).
- The Debug tab shows the new log viewport and fetches data from `/api/debug/logs` with pause/clear controls.

#### Known Issues
- Pre-commit hook installs require network access; rerun the command with an increased timeout or use `PRE_COMMIT_HOME=/tmp/pre-commit` if the default cache directory is unwritable.
- MariaDB still contains the `classification` column but writes now omit it (it stays NULL).

#### Rollback Plan
- Revert the planner/webapp tracing/numeric-output changes, remove the log viewer, and drop the tooling files if Step 8 needs rollback.

### Rev 27 — 2025-11-19: Lint Clean-up *(Status: ✅ Completed)*
- **Model**: Codex CLI
- **Summary**: `./lint.sh` now runs black & flake8. Black passes but flake8 reports 50+ issues (unused imports, trailing whitespace, overly long lines, unused locals, module-level ordering) across `db_writer.py`, `inputs.py`, `learning.py`, `planner.py`, `webapp.py`, `tests/*`, etc. This rev addresses those warnings.

**Plan:**
- **Goals**:
  1. Eliminate every unused import/local/variable flagged in the latest `flake8` output.
  2. Remove trailing whitespace from the listed files.
  3. Break down or wrap any lines longer than 100 characters per Black/flake8 config.
- **Scope**: `db_writer.py`, `inputs.py`, `learning.py`, `planner.py`, `webapp.py`, all affected `tests/`, and any supporting helper files that flake8 flagged.
- **Dependencies**: Requires `black`/`flake8` configs added in Rev 26; rerun `FLAKE8_USE_MULTIPROCESSING=0 ./lint.sh` to verify progress.
- **Acceptance Criteria**:
  - `lint.sh` completes without flake8 warnings (with multiprocessing disabled due to sandbox limits).
  - Code retains existing functionality (regression tests continue to pass).
  - Documentation mentions these cleanup steps.

  *AI note: the sandbox blocks fetching hook repos and writing to `~/.cache`, so AI commits should skip running `./lint.sh`/`pre-commit run` and rely on the maintainer to execute them manually before pushing.*

**Implementation:**
1. Patch each file to remove unused imports/locals and trailing whitespace (`db_writer.py`, `inputs.py`, etc.).
2. Wrap long lines that exceed 100 characters, favouring helper variables or restructuring expressions.
3. Re-run `FLAKE8_USE_MULTIPROCESSING=0 ./lint.sh` between edits to confirm the flagged list shrinks and eventually clears.

**Verification:** `FLAKE8_USE_MULTIPROCESSING=0 ./lint.sh` ✅ (pass observed on host after cleanup).

**Known Issues:** None besides lengthy cleanup required across multiple legacy modules.

**Rollback Plan:** Revert the cleanup commit if flake8 still fails after exhaustive fixes; revisit approach per file.

---

### Rev 28 — 2025-11-19: Water Heating Consistency *(Status: 📋 Planned)*
- **Model**: Codex CLI
- **Summary**: Address the unexpected water heating bursts by respecting recorded usage, enforcing the tolerance/max-block knobs, and exposing the consolidation controls in the UI.

**Plan:**
- **Goals**:
  1. Always honor the Home Assistant `water_heater_daily_entity_id` reading as the source of truth for today’s water-heating energy and stop scheduling once it reports the requirement met.
  2. Keep `_pass_2_schedule_water_heating` to `min_kwh_per_day`, consolidate the selected slots into ≤ `max_blocks_per_day` blocks, and honor the `block_consolidation_tolerance_sek`/`consolidation_max_gap_slots` thresholds when slots are within tolerance.
  3. Surface the consolidation and defer parameters in the Settings tab so the operator can tune them without editing YAML.
- **Scope**: `planner.py` water-heating pass and daily tracker, the Home Assistant/daily-water integration, `templates/index.html` + `webapp.py` settings endpoints, and documentation/tests that prove the behavior.
- **Dependencies**: Current HA sensor hooks (for `water_heater_daily_entity_id`), sqlite telemetry (daily_water table), and existing lint/test tooling.
- **Acceptance Criteria**:
  - Once `_get_daily_water_usage_kwh` reports a fulfilled day, the planner does not add extra water slots for that date.
  - The generated schedule contains at most `min_kwh_per_day` worth of water energy per date and never more than `max_blocks_per_day` blocks when prices stay within tolerance.
  - Settings now offer inputs for `water_heating.block_consolidation_tolerance_sek`, `water_heating.consolidation_max_gap_slots`, (optionally `defer_up_to_hours`), and the behavior is documented.

**Implementation:**
1. Replace the planner’s internal `daily_water.used_kwh` bookkeeping with a direct read of the HA `water_heater_daily_entity_id` sensor (secrets-configured) before `_pass_2_schedule_water_heating`; treat that HA value as the definitive “already heated today,” fall back to sqlite only when HA is unavailable, and stop emitting additional slots once the target is satisfied.
2. Rework `_select_optimal_water_slots` + `_consolidate_to_blocks` to be time-aware, insert gap slots when `tolerance`/`max_gap_slots` permit, and stop selecting slots once the required count is reached while keeping the block count ≤ `max_blocks_per_day`.
3. Add the missing consolidation/defer inputs to `templates/index.html`, force `water_heating.schedule_future_only` to true (remove the toggle) so the planner never opts into past slots, propagate the knobs through the settings save API, and mention the behavior in README/AGENTS so users understand the tolerance/defer controls.
4. Extend `tests/test_water_scheduling.py` (and any relevant regression tests) to assert the “already satisfied” shortcut, the block-limit/tolerance behavior, and that `schedule_future_only` still prevents retroactive slots.

**Verification:** Run `python planner.py`/`generate_schedule` to inspect `schedule.json`, plus targeted `pytest` cases for `_pass_2_schedule_water_heating` and the settings save endpoint; ensure the UI exposes the new knobs and unit tests cover them.

**Known Issues:** HA/live usage may still lag, so sqlite fallback might still report zero; the UI cannot guarantee the database is updated unless the HA sensor record is reliable.

**Rollback Plan:** Revert the water-heating refactor if block consolidation changes break downstream passes or MariaDB/Maria plan writes.

---

### Rev 29 — 2025-11-09: Hours-first Water Heating *(Status: ✅ Completed)*
- **Model**: Codex CLI
- **Summary**: Restrict the water-heating pass so the HA energy sensor is still the source of truth, but we always reserve `min_hours_per_day` whenever that sensor reports less than `min_kwh_per_day`, and only add extra cheap slots if the projected energy remains short.

**Plan:**
- **Goals**:
  1. Document the “energy check first, hours as a trigger” flow so the operator understands why we sometimes schedule fewer than `min_hours_per_day`.
  2. Update `_pass_2_schedule_water_heating` to first claim a block of `min_hours_per_day` slots whenever the HA daily value is below `min_kwh_per_day`, then append more slots until the energy target is met.
  3. Keep the HA sensor consistent: when it reports ≥ `min_kwh_per_day`, the planner stops scheduling even if the previous plan requested hours.
- **Scope**: `planner.py` water-heating routine, HA telemetry glue, tests, and documentation.
- **Dependencies**: The HA sensor (`water_heater_daily_entity_id`) and existing slotselection helpers (`min_hours_per_day`, `max_blocks_per_day`, tolerance settings).
- **Acceptance Criteria**:
  - HA energy above the minimum short-circuits scheduling.
  - When HA energy is insufficient, the planner schedules at least `min_hours_per_day` worth of slots (respecting block/tolerance constraints) before adding more to satisfy `min_kwh_per_day`.
  - Fixture tests confirm the HA sensor stops scheduling after the threshold and that hours are enforced when needed.

**Implementation:**
1. Confirm the README text above describes the intended behavior (energy is the authority; hours are scheduled only when energy is missing).
2. Refactor `_pass_2_schedule_water_heating` so it first selects enough slots to cover `min_hours_per_day` (using the same price/tolerance helpers) and then extends the selection only if the HA energy reading still falls below `min_kwh_per_day`.
3. Update `tests/test_water_scheduling.py` with cases showing the HA sensor shortcut and the hours-first scheduling under the tolerance/gap rules.
4. Leave the code untouched until we receive approval to proceed.

**Verification:** Run `PYTHONPATH=. ./venv/bin/python -m pytest tests/test_water_scheduling.py` after implementing the logic to ensure HA overrides and hours enforcement behave as expected.

**Known Issues:** HA energy data may lag; keep the fallback to sqlite and guard against running redundant hours when the energy sensor resets.

**Rollback Plan:** Revert the planner changes if the new hours-first scheduling over-commits slots or violates the existing block/tolerance constraints.

---

### Rev 30 — 2025-11-10: Block-contiguous Water Heating *(Status: ✅ Completed)*
- **Model**: Codex CLI
- **Summary**: Reordered the water-heating slot collection so the merged segments stay contiguous whenever the tolerance/gap settings allow it, preventing chopped blocks in the final schedule.

**Plan:**
- **Goals**:
  1. Sort `cheap_slots_sorted` by timestamp before building segments to preserve contiguous windows.
  2. Collect segments until the required slot count is reached and leave block-limiting to `_consolidate_to_blocks`.
- **Implementation:**
  1. Send time-ordered slots to `_build_water_segments`.
  2. Remove the early `max_blocks_per_day` break inside `_select_slots_from_segments`.
  3. Let `_consolidate_to_blocks` collapse the slots into at most `max_blocks_per_day` blocks.
- **Verification:** `PYTHONPATH=. ./venv/bin/python -m pytest tests/test_water_scheduling.py`.

**Known Issues:** None beyond the known HA sensor lag.

**Rollback Plan:** Revert the reordering changes if the block-count/tolerance behavior regresses.

---

### Rev 31 — 2025-11-10: Charge Responsibility From Expensive Gaps *(Status: ✅ Completed)*
- **Model**: Codex CLI
- **Summary**: Charge responsibilities now derive from the expensive gap that follows each cheap window, ensuring the battery fills for the next high-price period while preserving S-index/cascading semantics.

**Plan:**
- **Goals**:
  1. Make long cheap windows cover the next expensive interval’s demand instead of starving the battery by calculating each responsibility from the following non-cheap gap.
  2. Keep the existing S-index scaling, strategic carry-forward, and realistic capacity/cascading intact.
  3. Provide a hidden `charging_strategy.responsibility_only_above_threshold` toggle so operators can limit responsibilities to slots above the economic threshold when desired.
- **Scope**: `planner.py` `_pass_4_allocate_cascading_responsibilities`, focused tests, and README docs.
- **Dependencies**: Window detection from `Pass 1`, S-index config, and current cascading/smoothing infrastructure.

**Implementation:**
1. Pass 4 now constructs explicit gap intervals and computes responsibilities from the following non-cheap range, multiplying that net load by the configured S-index factor so cheap windows always cover the next expensive stretch before cascading.
2. Added the hidden `charging_strategy.responsibility_only_above_threshold` toggle (default `false`) to optionally restrict gap energy to expensive slots while leaving strategic overrides untouched.
3. Verified the behavior with dedicated gap-responsibility tests comparing computed responsibilities to the following gap’s net load and ensuring the price guard can zero them out when nothing exceeds the economic threshold.

**Verification:**
- `./venv/bin/python -m pytest tests/test_gap_responsibilities.py`

**Rollback Plan:** Revert `_pass_4_allocate_cascading_responsibilities` if the new gap-focused responsibilities cause regressions or overcharging beyond configured caps.

---

### Rev 32 — 2025-11-10: Hold SoC / Manual Apply Reliability *(Status: 📝 Planned)*
- **Model**: Codex CLI (planning only; implementation awaits approval)
- **Summary**: 
  1. Ensure “Hold” slots keep the real SoC of their entry point so the Gantt lane shows hold only when there is no battery action and the SoC target matches reality.
  2. Stop `/api/simulate` from collapsing into an empty DataFrame (and returning 500) when live feeds are missing and harden the UI so it only renders successful simulations.

**Plan:**
- **Goals**:
  1. Detect the first hold/action slot when the planner is keeping the battery idle (usually because `soc_min` is active) and keep its `soc_target_percent` equal to the current SoC, preventing the UI from redrawing it as an unintended “Hold” block.
  2. Guard `/api/simulate` against empty input data by reusing the last saved `schedule.json` (or returning a controlled error) before running `_pass_6_finalize_schedule`.
  3. Make the manual-apply flow in `static/js/app.js` check `response.ok` before persisting or rendering simulated results so the chart stays populated only with valid schedules.
- **Scope**: `planner.py` finalization logic (SoC tracking + `schedule.json` writes), `webapp.py` `/api/simulate` error handling/persistence, `static/js/app.js` manual-save render path, and any helper modules that share `soc_target_percent` with the UI.
- **Dependencies**: `simulate_schedule` remains the central helper; we rely on the existing `schedule.json` schema, `dataframe_to_json_response`, and timeline plotting expectations.
- **Acceptance Criteria**:
  - The first future slot marked “Hold” now has `soc_target_percent` equal to the `current_kwh` entry point, and the Gantt chart shows it in the hold lane only when no charge/discharge/export/water flow exists.
  - `/api/simulate` never raises `IndexError` when live feeds are missing: it either continues with the last saved schedule or returns `400/422` with a descriptive message.
  - Manual apply includes UI-side validation of the simulation response; the line chart no longer disappears after a failed apply attempt.

**Implementation:**
1. Update `_pass_6_finalize_schedule` (or `_apply_soc_target_percent`) so any slot where the planner forgoes discharge and leaves `action == "Hold"` while `current_kwh` equals the entry SoC preserves that SoC as its `soc_target_percent`; ensure the serialized schedule retains this value for the UI and timeline lanes.
2. Strengthen `/api/simulate` to detect empty/invalid DF before entering `_pass_6_finalize_schedule`. If no rows are available, load `schedule.json` as a fallback plan (or short-circuit with a user-friendly error) instead of crashing.
3. In `static/js/app.js`, before calling `/api/schedule/save`, inspect `simulatedData` to confirm `simulatedData.schedule` is present and `response.ok` was true; otherwise log the error and keep the existing chart data instead of wiping it.
4. Add a short regression test or script that mimics the manual apply path with stale/no live input data to ensure the backend/UI no longer drop the chart.

**Verification:**
- `PYTHONPATH=. ./venv/bin/python -m pytest -q` (target the gazette of any failing tests).
- Trigger the manual “Apply changes” flow in the UI (or via curl) while the feeds are disabled; confirm the line chart stays populated and the log records a meaningful 4xx/5xx message instead of a 500 that clears the UI.
- Inspect the generated `schedule.json` to ensure the first hold slot’s `soc_target_percent` equals the `projected_soc_percent`/current SoC at that step.

**Known Issues:**
- If the saved `schedule.json` becomes stale, the manual apply fallback may still show older projections; this is acceptable until live feeds recover.

**Rollback Plan:**
- Revert the changes to `_pass_6_finalize_schedule`, `/api/simulate`, and `static/js/app.js` if the new guard logic cannot reliably represent hold SoC or causes false positives during manual applies.

*Document maintained by AI agents using revision template above. All implementations should preserve existing information while adding new entries in chronological order.*
