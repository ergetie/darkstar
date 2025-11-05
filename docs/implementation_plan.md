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

*Document maintained by AI agents using revision template above. All implementations should preserve existing information while adding new entries in chronological order.*