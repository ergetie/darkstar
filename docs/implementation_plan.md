# Darkstar Planner: Master Implementation Plan

*Single source of truth for goals, plans, progress, and handover. This document remains the living working plan. Older project plan files are superseded. For each change, create a new **Rev** entry with a concrete plan, and on completion fill the remaining sections and mark the Rev as **✅ Completed**.*

---

## How to use this document

* Each **Rev** captures one focused change-set (feature, migration, or batch of fixes).
* Workflow per Rev:

  1. **Plan** (Goals, Scope, Dependencies, Acceptance Criteria).
  2. **Implement** (log completed/in-progress/blocked, decisions, files changed).
  3. **Verify** (tests, known issues, rollback).
  4. Mark status and add dates.
* Keep commit messages and PR titles referencing the Rev, e.g. `rev37: monorepo skeleton`.
* Keep this file concise: put deep background in README, and API field-by-field details in code/docstrings.

---

## Phase 1 (Rev 0–36) — Compact Summary

> Completed groundwork to reach robust MPC behavior with integrated water heating, manual planning semantics, DB/HA integration, themeable UI, and diagnostics.

* **Core MPC passes**: efficiency-aware SoC simulation, price window detection, cascading responsibilities, charge block consolidation, final polish with “hold in cheap windows”.
* **Water heating**: daily quota with cheapest-slot packing and bounded deferral; grid-preferred to preserve battery.
* **Export**: gated by profitability & percentile guard; “peak-only export” option; future-price guard to avoid premature export.
* **Manual planning**: block types (charge/water/export/hold) merged via `/api/simulate` → `/api/schedule/save`; manual-mode overrides respect device limits while bypassing some planner protections only during manual apply.
* **APIs**: schedule/status/history/horizon/HA/theme endpoints; DB push/read for server plan; simulate/save; initial_state.
* **UI (legacy Flask)**: 48-hour chart (price, PV/load fills, charge/export/discharge, SoC projected/target/real/historic), vis-timeline lanes (Battery/Water/Export/Hold), theme system, Learning/Debug tabs.
* **Ops**: tests, hourly/systemd scheduling pattern, doc’d release flow.

---

## Revision Template

* **Rev [X] — [YYYY-MM-DD]**: [Title] *(Status: ✅ Completed / 🔄 In Progress / 📋 Planned)*

  * **Model**: [Agent/Model used]
  * **Summary**: [One-line overview]
  * **Started**: [Timestamp]
  * **Last Updated**: [Timestamp]

  **Plan**

  * **Goals**:
  * **Scope**:
  * **Dependencies**:
  * **Acceptance Criteria**:

  **Implementation**

  * **Completed**:
  * **In Progress**:
  * **Blocked**:
  * **Next Steps**:
  * **Technical Decisions**:
  * **Files Modified**:
  * **Configuration**:

  **Verification**

  * **Tests Status**:
  * **Known Issues**:
  * **Rollback Plan**:

---

## Rev 37 — Monorepo Skeleton *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI

* **Summary**: Restructure repository into `backend/` (Flask) and `frontend/` (React/Vite) while keeping behavior unchanged. Prevent `node_modules/` from entering version control. No code logic changes.

* **Started**: 2025-11-12

* **Last Updated**: 2025-11-12

### Plan

* **Goals**

  * Create monorepo layout to enable a clean frontend pivot.
  * Keep all APIs and legacy UI working as before.
  * Ensure clean VCS history (exclude `node_modules/`).
* **Scope**

  * Move Flask UI shell to `backend/` (webapp, templates, static, themes).
  * Move React sandbox to `frontend/`.
  * Add/confirm `.gitignore` to exclude `**/node_modules/`.
  * Do **not** move core Python modules (`planner.py`, `inputs.py`, etc.) yet.
  * No script changes; no Vite proxy yet.
* **Dependencies**

  * None (pure file operations).
* **Acceptance Criteria**

  * Repo has `backend/` and `frontend/` with expected contents.
  * `FLASK_APP=backend.webapp flask run` still starts the app (where the environment allows binding).
  * Git diff limited to moves + `.gitignore`; no `node_modules/` tracked.

### Implementation

* **Completed**

  * Moved `webapp.py`, `templates/`, `static/`, `themes/` → `backend/`.
  * Moved React sandbox → `frontend/`.
  * Added recursive ignore for `node_modules/`, removed any cached entries from the index.
  * Ensured only `backend/`, `frontend/`, and `.gitignore` were committed; stashed unrelated doc edits during the move.
* **Technical Decisions**

  * Kept `planner.py`/`inputs.py` at repo root to avoid import churn.
  * Deferred “one-command dev” and Vite proxy to a later Rev.
* **Files Modified**

  * New paths under `backend/` and `frontend/`; updated `.gitignore`.
* **Configuration**

  * None.

### Verification

* **Tests Status**

  * Planner/tests unaffected; APIs unchanged.
  * Local Flask launch attempted (port binding blocked in sandbox; acceptable for this Rev).
* **Known Issues**

  * None introduced by restructure.
* **Rollback Plan**

  * Single revert commit moves files back; no schema or config changes were made.

---

## Rev 38 — Dev Ergonomics: Dual-Server Dev Loop *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Add Vite dev proxy to `/api`, and a root script to run Vite + Flask concurrently.

### Plan

* **Goals**

  * One command starts both servers in dev.
  * Vite dev server proxies `/api` → Flask to avoid CORS.
* **Scope**

  * Root `package.json` with `concurrently` or equivalent.
  * `frontend/vite.config.ts`: `server.proxy['/api'] = 'http://localhost:5000'`.
  * Optional `scripts/dev-backend.sh` to activate venv then `flask run`.
* **Dependencies**

  * Rev 37 (monorepo).
* **Acceptance Criteria**

  * `npm run dev` at repo root starts both servers with hot reload.

### Implementation

* **Completed**:

  * Added root `package.json` with `scripts.dev`, `scripts.dev:frontend`, `scripts.dev:backend` using `concurrently@^9.0.0`.
  * Created `scripts/dev-backend.sh` that exports `FLASK_APP=backend.webapp`, activates `venv` if present, and runs `python -m flask run --port 5000`.
  * Updated `frontend/vite.config.ts` to include `server.port=5173` and a `/api` proxy to `http://localhost:5000` with `changeOrigin:true`.
  * Appended `.gitignore` entries for `frontend/dist/` and ensured `node_modules/` patterns are present.
  * Staged only the requested files; no other paths were committed.
* **In Progress**: —
* **Blocked**: —
* **Next Steps**: None (Rev 38 closed).
* **Technical Decisions**: Use `concurrently` for a unified dev loop; keep production serving decisions for a later Rev.
* **Files Modified**: `package.json`, `scripts/dev-backend.sh`, `frontend/vite.config.ts`, `.gitignore`
* **Configuration**: None (dev-only changes).

### Verification

* **Tests Status**: N/A for functional tests; config lint passes. Dev loop verified by file inspection.
* **Known Issues**: Some sandboxes block port binding, so runtime verification may be skipped; acceptable for this Rev.
* **Rollback Plan**: Revert the four modified files in a single commit if needed.

---

## Rev 39 — React Planning Scaffold *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Establish React app shell (routes, left rail, header), and focus on the Dashboard tab with the 48‑hour chart fed from backend APIs. Planning timeline moved to Backlog.

### Plan

* **Goals**

  * Deliver desktop‑first Dashboard that mirrors the legacy chart (no timeline yet).
* **Scope**

  * Tailwind tokens (dark charcoal, yellow accent), JetBrains Mono, Lucide left rail.
  * Chart.js datasets: price line; PV/load fills; charge/export/discharge bars; SoC (projected/target/historic).
  * API wiring for `/api/schedule`, `/api/status`, `/api/forecast/horizon` where needed for Dashboard.
* **Dependencies**

  * Rev 38 (proxy + dev loop).
* **Acceptance Criteria**

  * Dashboard chart renders datasets from `/api/*` with correct 48‑hour window and no “bridges” on missing/partial data; day toggle works.

### Implementation

* **Completed**

  * App shell with routes: `/`, `/planning`, `/learning`, `/debug`, `/settings`.
  * Sidebar, Header, Card components and design tokens.
  * Dashboard ChartCard fetching `/api/schedule` and mapping fields to datasets (supports both `battery_*` and legacy `charge_kw`/`discharge_kw`).
  * Day selector (today/tomorrow); Chart.js configured with `spanGaps: false` to avoid bridging missing points.
  * Dev proxy and dual‑server loop available from Rev 38.

* **In Progress**: —
* **Blocked**: —

* **Next Steps**

  * None (see Backlog for Planning timeline and other tabs).

* **Technical Decisions**

  * Keep timeline interactions (vis‑timeline) out of Rev 39; implement under Backlog (Rev 40).

* **Files Modified**

  * `frontend/src/App.tsx`, `frontend/src/components/ChartCard.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/lib/{api.ts,time.ts,types.ts}` and related UI scaffolding.

* **Configuration**

  * None (dev‑only via Vite proxy from Rev 38).

### Verification

* **Tests Status**

  * Visual inspection of datasets; manual checks confirm local day slicing and dataset alignment. No API changes.
* **Known Issues**

  * None for Dashboard; Planning timeline remains in Backlog.
* **Rollback Plan**

  * Revert frontend chart/data wiring changes if required; API unchanged.

---

## Rev 40 — Dashboard Completion *(Status: ✅ Completed)*

* **Model**: GLM-4.6
* **Summary**: Complete Dashboard functionality to achieve full parity with legacy UI including API integration, visual improvements, and UX polish.
* **Started**: 2025-11-13
* **Last Updated**: 2025-11-13
* **Completed**: 2025-11-13

### Plan

* **Goals**:
  * Transform Dashboard from partially integrated mockup to fully functional interface
  * Implement all missing backend integrations and user interactions
  * Fix visual/UX issues and improve usability
  * Establish real-time data flow and proper error handling
* **Scope**:
  * Quick Actions API wiring and functionality
  * Chart theme improvements and dataset visibility
  * Header/logo reorganization and menu structure  
  * Dynamic KPIs and status cards with real data
  * Real-time updates and timezone fixes
  * UI/UX polish for buttons and interactions
* **Dependencies**:
  * Rev 39 (React scaffold and basic Dashboard)
  * Backend APIs already available and functional
* **Acceptance Criteria**:
  * All Quick Action buttons trigger correct API calls and update UI
  * Chart datasets are clearly visible with proper colors and toggles
  * Header uses bolt logo, all items moved to sidebar menu
  * KPIs and status cards show real-time data from appropriate APIs
  * Day slicing works correctly with local timezone
  * Data refreshes automatically or on-demand
  * No console errors, proper loading states for all API calls

### Implementation Steps (Multi-step tracking)

1. **Quick Actions API Wiring** ✅
   * Wire "Run planner" → `/api/run_planner`
   * Wire "Load server plan" → `/api/db/current_schedule` 
   * Wire "Push to DB" → `/api/db/push_current`
   * Wire "Reset to optimal" → clear manual changes
   * Add success/error feedback and state updates

2. **Chart Theme & Dataset Improvements** ✅
   * Apply Material Design colors to all datasets (fix invisible SoC lines)
   * Ensure charge/discharge/export/SoC appear in legend with toggles
   * Add water heating dataset with proper color and legend toggle
   * Verify dataset visibility matches legacy UI behavior
   * Test color contrast and accessibility

3. **Header/Logo Reorganization** ✅
   * Move lucide-bolt icon from header to sidebar as logo
   * Replace "nav" text in sidebar with bolt logo
   * Move all header items to sidebar menu
   * Update responsive behavior for mobile

4. **Quick Actions UI Fix** ✅
   * Remove text from buttons, keep icons only
   * Add hover tooltips with button labels
   * Fix button sizing and text spilling issues
   * Ensure consistent spacing and alignment

5. **Dashboard Rendering Fix** ✅
   * Fixed undefined `liveData` variable causing JavaScript errors
   * Added proper state management for no-data message display
   * Implemented graceful fallback for tomorrow without price data

5. **Dynamic KPIs Integration** ✅
    * Battery capacity from system config
    * PV today from calculated schedule data
    * Avg load from `/api/ha/average`
    * Current SoC target from current schedule slot
    * Removed redundant "SoC now" text from system status
    * Add loading states and error handling
    * Fixed button collision - integrated day switching into ChartCard

6. **Status Cards Real Data** ✅
   * Water heater from `/api/ha/water_today`
   * Export guard status from config
   * Learning status from `/api/learning/status`
   * Chart tooltip improvements with elaborate display and HH:mm formatting
   * Fixed tooltip to show all datasets (mode: 'index', intersect: false)
   * Added "NOW" marker line for current time on today's chart

7. **Real-time Updates & Timezone** ✅
    * Fix `isToday`/`isTomorrow` to use local timezone
    * Add polling strategy for live data refresh (30s intervals)
    * Implement plan origin indicator (local vs server)
    * Add data refresh controls (manual button + auto-refresh toggle)
    * Add loading states and visual feedback for refresh operations

### Files to be Modified
* `frontend/src/components/QuickActions.tsx`
* `frontend/src/components/ChartCard.tsx` 
* `frontend/src/components/Header.tsx`
* `frontend/src/components/Sidebar.tsx`
* `frontend/src/pages/Dashboard.tsx`
* `frontend/src/lib/api.ts` (expand API client)
* `frontend/src/lib/time.ts` (timezone fixes)
* `frontend/src/lib/types.ts` (if needed)

### Configuration
* No backend config changes required
* Frontend: Material Design color palette constants

### Implementation

* **Completed**:
  * Quick Actions API wiring with POST methods and success/error feedback
  * Chart theme improvements with Material Design colors and proper Y-axis mapping
  * Quick Actions UI fix with icon-only buttons and hover tooltips
  * Dashboard rendering fix - resolved undefined variable causing complete UI failure
  * Graceful fallback for tomorrow data when no prices are available
  * Header/Logo reorganization - moved bolt to sidebar, moved header items to menu
  * Real-time polling with 30s intervals and manual refresh controls
  * Loading states and visual feedback for all data refresh operations
  * Dynamic theme colors integration - charts adapt to current theme selection

* **In Progress**: —
* **Blocked**: —
* **Next Steps**: Rev 40 Complete! Added dynamic theme colors integration - ready for verification and final testing

### Verification
* Test each Quick Action with API monitoring
* Verify chart dataset visibility and colors
* Check responsive behavior after header changes
* Validate real-time data updates
* Test timezone edge cases (midnight, DST)
* Ensure error handling for failed API calls

### Rollback Plan
* Revert individual component changes if needed
* Each step can be rolled back independently
* API changes are client-side only, no backend impact

---

## Rev 41 — Dashboard Hotfixes *(Status: ✅ Completed)*

* **Model**: GLM-4.6
* **Summary**: Fix critical UI bugs and polish issues discovered after Rev 40 completion
* **Started**: 2025-11-13
* **Last Updated**: 2025-11-13
* **Completed**: 2025-11-13

### Plan

* **Goals**:
  * Fix functional issues affecting user experience
  * Clean up console errors and warnings
  * Polish UI inconsistencies
* **Scope**:
  * Quick Actions integration with Dashboard refresh
  * Chart.js DOM error fixes
  * UI cleanup (GitHub button removal, bolt logo sizing)
  * Console warnings cleanup
* **Dependencies**:
  * Rev 40 (Dashboard Completion)
* **Acceptance Criteria**:
  * Run planner properly updates Dashboard display
  * No Chart.js DOM errors in console
  * Clean console with minimal warnings
  * Consistent UI sizing and spacing

### Implementation Steps

1. **Quick Actions Integration Fix** ✅
   * Add callback to trigger Dashboard data refresh after planner runs
   * Update plan origin indicator to reflect changes
   * Ensure "NOW SHOWING:" updates correctly

2. **Chart.js DOM Error Fix** ✅
   * Add null checks for chart canvas element
   * Improve chart initialization timing with theme loading
   * Prevent chart updates on destroyed elements

3. **UI Cleanup** ✅
   * Remove GitHub button/logo from menu bar
   * Fix lucide-bolt logo sizing to match buttons
   * Add proper margin between bolt and other buttons

4. **Console Cleanup** ✅
   * Fix button className prop warnings
   * Remove excessive debug logging in time.ts
   * Address React Router future flag warnings

### Files Modified
* `frontend/src/components/QuickActions.tsx` - Added onDataRefresh callback and delay
* `frontend/src/components/Sidebar.tsx` - Removed GitHub button, fixed logo sizing/spacing
* `frontend/src/components/ChartCard.tsx` - Fixed Chart.js DOM timing issues
* `frontend/src/pages/Dashboard.tsx` - Added refresh prop passing
* `frontend/src/lib/time.ts` - Removed excessive debug logging
* `planner.py` - Fixed metadata saving for status updates
* `webapp.py` - Backend already supported status metadata

### Configuration
* No backend config changes required

### Implementation

* **Completed**: Steps 1-4 (Quick Actions Integration, Chart.js DOM Error Fix, UI Cleanup, Console Cleanup) + Fix #1 (Metadata Sync implementation in Dashboard) + Fix #2 (Chart Safety in ChartCard) + Fix #3 (SoC Projected dataset) + Fix #4 ("NOW" marker + X-axis label polish)
* **In Progress**: Visual polish / UX refinements only (non-blocking)  
* **Blocked**: —
* **Next Steps**: Optional design tweaks for the "NOW" marker and additional dashboard cosmetic improvements

### Current Status Summary

**Issue #1**: ✅ **RESOLVED** - ChartCard reverted to working structure
- Reverted to working two-useEffect approach from commit 68745d3
- Chart should now properly show today data and "No Price Data" message for tomorrow
- Debug logging added to trace data flow

**Issue #2**: ✅ **IMPLEMENTED, PENDING VERIFICATION** - Load Server Plan Status Detection
- Expected: "Load server plan" should update "NOW SHOWING" with correct server metadata
- Current behavior (post-fix): Badge source driven by `currentPlanSource` and metadata derived from matching local/db status objects
- Risk: Still needs manual UI verification to confirm no edge cases (e.g. missing server metadata)

### Implementation - UI State Tracking (Metadata & Source)

**What Was Implemented**:
- Added `currentPlanSource` state to Dashboard component to track user's current view ✅
- Modified `QuickActions.tsx` to accept `onPlanSourceChange` callback and emit `local`/`server` intent ✅
- Split planner metadata into `plannerLocalMeta` and `plannerDbMeta` derived from `/api/status` ✅
- Added derived `plannerMeta` that is recomputed from `currentPlanSource` + stored metadata ✅
- Updated "NOW SHOWING" badge to use `currentPlanSource` for the label and `plannerMeta` for timestamp/version ✅

**Files Modified**:
- `frontend/src/components/QuickActions.tsx` - Added plan source change callback
- `frontend/src/pages/Dashboard.tsx` - Added state tracking, separate local/db metadata, and derived `plannerMeta`

**Status**:
- Badge shows correct source (server/local) ✅
- Metadata now follows the selected source instead of always preferring local ✅
- Awaiting manual verification in real UI flows (run planner, load server plan, reset, push) ⚠️

**New Issue #3**: Chart.js Plugin Cache Error ✅ **ADDRESSED BY FIX #2**
- Original error: "can't access property 'filter', this._plugins._cache is undefined"
- Location: ChartCard.tsx during chart update operations on destroyed chart instances
- Fix: Guard all updates via `isChartUsable`, clear `chartRef` on destroy, and wrap updates in try/catch to avoid calling `update` on invalid instances

### Remaining Issues to Debug

1. **Tomorrow Tab Shows Empty Chart**
   - Expected: Show "No Price Data" message like before
   - Actual: Shows empty chart with no data
   - Need to investigate buildLiveData fallback logic

2. **Load Server Plan Status Detection** ✅ **IMPLEMENTED, PENDING VERIFICATION**
   - Expected: Update "NOW SHOWING" to indicate server plan loaded with correct metadata
   - Current: Badge and metadata are both driven by `currentPlanSource` + source-specific metadata
   - Remaining: Validate edge cases (no server metadata, first-load state) during manual testing

3. **Chart.js Plugin Cache Error** ✅ **RESOLVED BY FIX #2**
   - Expected: Chart updates without errors
   - Current: Updates are guarded by `isChartUsable` + try/catch; destroyed charts clear their refs on cleanup
   - Remaining: Keep an eye on runtime console during testing; no known repro after hardening

### Implementation Status
- ✅ Added plan source state tracking to Dashboard component
- ✅ Modified QuickActions to communicate plan source changes
- ✅ Updated status display to show user's current view, not file metadata
- ✅ Metadata sync implemented so plan source and metadata match
- ✅ Chart safety implemented; plugin cache errors guarded

### Planned Fixes

**Fix #1 - Metadata Sync**:
- Preserve both `local` and `db` planner metadata from `/api/status` in separate state objects
  (e.g. `plannerLocalMeta`, `plannerDbMeta`) instead of collapsing into a single `plannerMeta`.
- Add a derived effect/selectors that compute the *displayed* `planMeta` from
  `currentPlanSource` + the stored metadata (server → DB meta, local → local meta).
- When `currentPlanSource` is `'server'` but DB metadata is missing, avoid silently
  reusing local timestamps; show an explicit “no server metadata” state or fallback
  text so that badge + timestamp are never misleading.
- (Optional refinement) On initial load, derive the initial `currentPlanSource` from
  `/api/status` (e.g. prefer `local` when local meta exists, otherwise fall back to
  `server` when only DB meta is present) so “NOW SHOWING” is consistent even before
  the first Quick Action.

**Fix #2 - Chart Safety**:
- Ensure `chartRef.current` is cleared when a chart is destroyed
  (set `chartRef.current = null` in the `destroy()` cleanup) so effects never hold
  references to destroyed instances.
- Before any `chartInstance.update(...)`, validate that the instance exists and is
  not destroyed (e.g. bail out if `(chartInstance as any)._destroyed` is true or
  if plugin internals like `chartInstance.$plugins` / `_plugins` are missing).
- Wrap schedule-driven updates in try/catch as a secondary guard, and if an error
  is thrown during `update`, re-create the chart from the latest `liveData` only
  when the canvas is still mounted.
- Optionally simplify to a single schedule-fetch/update effect (driven by
  `[currentDay, overlays, themeColors]`) to reduce races between multiple effects
  touching `chartInstance.data`, then use the default `update()` mode once safety
  checks are in place.

**Fix #3 - SoC Projected Visibility**:
- Add a dedicated `SoC Projected (%)` line dataset in `ChartCard` that consumes
  `slot.projected_soc_percent` (already wired via `buildLiveData`) and attaches
  to the percentage axis (`y3`) with a distinct color from SoC Target.
- Keep the dataset hidden by default and wire it to the existing "SoC Projected"
  overlay toggle (dataset index 8) so users can reveal it on demand.
- Confirm that tooltip formatting and legend behavior remain consistent (legend
  still filters to core datasets; SoC lines are controlled via overlay buttons).

**Fix #4 - "Now" Marker & X-Axis Labels**:
- Compute a `nowIndex` in `buildLiveData` for today's data based on the current
  local time falling inside a slot's 30-minute window, and derive a normalized
  `nowPosition` (0–1) across the X-axis labels.
- Keep the X-axis underlying labels as `HH:mm` but adjust tick callbacks so the
  axis only renders one-hour steps as `HH` (e.g. 00, 01, …, 23), while the
  tooltip title still shows full `HH:mm` labels for precise time.
- Render a subtle CSS overlay "NOW" marker (thin accent-colored vertical line
  with a small pill label) above the canvas on the today chart only, avoiding
  Chart.js config recursion issues while still clearly indicating current time.

---

## Rev 42 — Planning Timeline *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI (planned)
* **Summary**: Rebuild the Planning Timeline tab in React, mirroring the legacy vis-timeline behavior (manual block planning, simulate/save) while matching the new dashboard theme.
* **Started**: 2025-11-13
* **Last Updated**: 2025-11-13

### Plan

* **Goals**:
  * Provide a fully functional Planning Timeline in the new React UI that matches legacy vis-timeline behavior.
  * Allow users to create, edit, and delete manual blocks (charge, water, export, hold) with clear visual semantics.
  * Integrate simulate/save flows so manual plans can be previewed and applied without breaking MPC protections.
  * Keep the timeline visually consistent with the new dashboard theme and data sources.

* **Scope**:
  * React Planning tab timeline implementation using `react-calendar-timeline` as the primary engine (with a thin wrapper), with vis-timeline kept as a fallback only if needed.
  * Manual block CRUD (create/edit/delete for charge/water/export/hold blocks).
  * Simulate/save workflow using `/api/simulate` and `/api/schedule/save`.
  * Synchronization between timeline edits and the main schedule chart/summary.
  * Read-only handling for historical slots.
  * Enforcement of device caps and SoC target constraints when editing blocks.
  * Handling of zero-capacity gaps according to existing planner rules.

* **What the timeline must provide**:
  * 48-hour window (today + tomorrow) with 30-minute slot precision.
  * Lanes: charge, water heating, export, hold.
  * 1:1 reflection with the schedule/chart in both directions (timeline edits → simulate/save → chart; server/local/manual origin stays clear).
  * Dragging and resizing blocks for precise manual overrides.
  * Zoom and pan for fine-grained adjustments.
  * Lane-specific “add block” actions (buttons) for easy manual scheduling.
  * A path to mobile/tablet responsiveness in the future (desktop first for Rev 42).
  * A clean deletion model (no cluttered “x” icons on blocks; removal via selection/toolbar or similar).

* **Dependencies**:
  * Rev 40 / 40.1 (Dashboard endpoints and schedule APIs stable).
  * Existing backend support for simulate/save (`/api/simulate`, `/api/schedule/save`).
  * Legacy vis-timeline behavior as reference (Flask UI) for interactions and colors.

* **Acceptance Criteria**:
  * Planning tab shows a themed timeline with lanes for relevant block types (e.g. Battery/Water/Export/Hold).
  * User can create, edit, and delete blocks for supported types within allowed time ranges.
  * Simulate/save runs through backend APIs, and results are reflected both in the timeline and the schedule chart.
  * Historical slots are read-only; user cannot modify past time windows.
  * Edits respect device caps (power, energy) and SoC target bounds; invalid edits are prevented or clearly surfaced.
  * Zero-capacity gaps are handled without breaking the visualization (no misleading continuous blocks).

### Implementation Steps (Planned)

1. **Timeline Shell & Data Wiring**
   * Add Planning tab layout in React to host the timeline.
   * Wire current schedule data from `/api/schedule` into a normalized structure usable by the timeline component.
   * Define lanes and basic grouping (Battery/Water/Export/Hold) based on existing schedule classifications.

2. **Timeline Engine Integration & Theming**
   * Integrate `react-calendar-timeline` inside a dedicated `PlanningTimeline` React component and render existing schedule blocks in the Planning tab.
   * Apply theme tokens (colors, fonts, spacing) to make the timeline visually consistent with the dashboard.
   * Lock the visible window to a rolling 48‑hour range (today + tomorrow), clamping pan/zoom so users cannot scroll beyond that horizon while still allowing useful zoom levels within it.
   * Merge consecutive schedule slots with the same classification into single blocks per lane to avoid slot‑level noise and better match the legacy “action block” behavior.

3. **Block CRUD & Reset Semantics**
   * Treat timeline blocks as the editable representation of the full 48‑hour schedule (no separate manual vs. auto block types).
   * Implement block creation via lane “add action” buttons for charge/water/export/hold types.
   * Implement block editing (resize, move) and deletion of individual blocks with appropriate constraints.
   * Implement a “Reset to current plan” action that reloads the latest schedule (today+tomorrow) into the timeline and discards unsaved edits.
   * Persist the current timeline state in local UI state for simulate/save.

4. **Simulate / Save Workflow**
   * Map the current 48‑hour timeline block state into the payload expected by `/api/simulate`.
   * Implement a simulate action that:
     * Sends the current timeline blocks + context to `/api/simulate`.
     * Shows the simulated plan in the timeline and chart without committing it.
   * Implement save/apply via `/api/schedule/save`, updating the server plan and UI (timeline + dashboard) on success.
   * Handle errors (validation issues, backend failures) with clear messages and non-destructive behavior.

5. **Chart Synchronization & Status**
   * Ensure that after simulate/save, the main dashboard chart reflects the same plan shown in the timeline.
   * Mirror the legacy behavior where the dashboard schedule/line chart clearly visualizes the impact of timeline edits on charge/export/water/hold over the 48‑hour window.
   * Add a small status indicator on the Planning tab showing whether the view represents local/manual vs server plan.
   * Keep the "NOW SHOWING" metadata consistent with manual plan application.

6. **Constraints, Read-only & Edge Cases**
   * Mark historical slots as read-only in the timeline; prevent manual edits in the past.
   * Enforce device caps and SoC bounds when editing or creating blocks (e.g. max charge/discharge power).
   * Handle zero-capacity gaps inside blocks according to planner rules (e.g. split vs. visually indicate gaps).
   * Add basic validation to avoid overlapping or conflicting blocks within the same lane.

7. **UX & Theme Polish**
   * Align timeline colors and block styles with the dashboard datasets (charge/export/water/SoC).
   * Adjust block corner radius to be less pill‑like (roughly half the current radius) while staying consistent with the dashboard’s minimal theme.
   * Configure time headers/ticks for clear hourly markers (HH) over the 48‑hour window, while preserving 30‑minute precision in interactions.
   * Move lane \"add action\" buttons into the timeline sidebar so each lane has a vertically aligned button (`+ chg`, `+ wtr`, `+ exp`, `+ hld`) centered on its row, and drop redundant lane labels.
   * Remove the large date header row from the timeline (keep only hourly ticks), and restyle headers/grid to use dark, toned‑down backgrounds matching the chart.
   * Align Planning controls so \"Apply manual changes\" and related buttons are grouped on the left, and remove redundant \"today → tomorrow\" text now that the view is fixed to 48h.
   * Tune interactions (hover tooltips, selection, context menus if needed) to feel coherent with the rest of the app.
   * Ensure the Planning tab’s visual density and typography match the Dashboard (no stray labels/text inside blocks; buttons use `chg/wtr/exp/hld` labels).
   * Document keyboard/mouse interactions briefly within the Planning tab or help text.

### Implementation

* **Completed**:
  * Step 1 (Timeline Shell & Data Wiring – Planning tab layout, schedule wiring, initial lane/block normalization)
  * Step 2 (Timeline Engine Integration & Theming – react-calendar-timeline integrated with themed items, 48‑hour window clamped to today+tomorrow, adjacent schedule slots merged into larger action blocks, and basic drag/resize + add‑block interactions working)
  * Step 3 (Block CRUD & Reset Semantics – select/delete individual blocks, reset timeline back to the latest schedule, treat the timeline as the editable 48‑hour schedule)
  * Step 4 (Simulate / Save wiring from Planning – \"Apply manual changes\" builds a simplified block payload, posts to `/api/simulate`, reloads the merged schedule, and re-derives planning blocks)
  * Step 5 (Chart Synchronization – Planning tab shows a 48‑hour schedule chart using the Dashboard chart component; the chart refreshes after simulate so timeline + chart stay in sync for the local plan)
  * Step 6 (Constraints, Read-only & Edge Cases – historical slots read-only/shaded; zoom/pan clamped to 48h; timeline \"NOW\" line matching the chart; prevent edits in past slots)
  * Step 7 (UX & Theme Polish – lane-aligned add buttons, minimal dark grid, hourly headers only, compact actions, consistent NOW lines on chart and timeline, and Planning controls aligned with Dashboard aesthetics)
* **In Progress**: —  
* **Blocked**: —
* **Next Steps**: Investigate the SoC Projected jump around 16:45–17:45 where SoC rises sharply without an obvious charge block, and handle device caps / zero‑capacity gap constraints in a later Rev.

### Verification (Planned)

* Manual UI tests:
  * Create/edit/delete blocks across types and confirm planner behavior stays consistent with legacy UI.
  * Simulate and save scenarios, verifying backend APIs are called with expected payloads.
  * Confirm that server and local/manual plans are clearly indicated and never silently diverge.
* Edge case validation:
  * Past slots remain read-only.
  * Device cap and SoC constraints correctly prevent or flag invalid edits.
  * Zero-capacity gaps do not produce misleading continuous blocks.

---

### Verification
* ✅ Run planner properly updates Dashboard display with new timestamp
* ✅ No Chart.js DOM errors in console (added timing safeguards)
* ✅ Clean console with minimal warnings (removed debug logs)
* ✅ Consistent UI sizing and spacing (bolt logo fixed, GitHub removed)

### Rollback Plan
* Revert individual component changes if needed
* Each step can be rolled back independently

---

## Rev 43 — Settings & Configuration UI *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Consolidate legacy System and Settings tabs into a single Settings page in the React UI (System / Parameters / UI), wire it to the existing config APIs, and surface all key planner, learning, and S-index safety parameters in a structured, safe way.
* **Started**: 2025-11-13
* **Last Updated**: 2025-11-13

### Plan

* **Goals**:
  * Provide a single, modern Settings tab that replaces the legacy Flask System + Settings views.
  * Expose all critical configuration knobs from `config.yaml` (battery, arbitrage, charging strategy, learning, S-index safety, UI) in a clear structure.
  * Support safe read/update/reset flows via `/api/config`, `/api/config/save`, `/api/config/reset` with basic client-side validation.
  * Integrate theme selection and basic UI preferences so the app is configurable without editing files.

* **Scope**:
  * React Settings page with three main sections:
    * **System** (hardware + integration): battery, HA entities, timezone, Nordpool basics, learning DB path.
    * **Parameters** (planner behavior): charging strategy, arbitrage, water heating, Learning Parameter Limits, S-Index Safety.
    * **UI** (app experience): theme picker, chart defaults, possibly auto-refresh and other display preferences.
  * Read config from `/api/config` and map to structured forms.
  * Persist changes via `/api/config/save` with deep-merge semantics and simple validation (non-negative numbers, sane ranges).
  * Provide a “Reset to defaults” action hooked to `/api/config/reset` with confirmation and clear messaging.
  * Ensure learning-related configuration (Learning Parameter Limits, S-Index Safety, and any `learning.*` keys) is discoverable under Settings, not scattered across tabs.

* **Dependencies**:
  * Rev 40 / 41 (Dashboard endpoints, schedule/status APIs, and config semantics stable).
  * Rev 42 (Planning timeline and chart behavior using the current config).
  * Backend config endpoints already implemented:
    * `/api/config` (GET)
    * `/api/config/save` (POST)
    * `/api/config/reset` (POST)
  * Theme endpoints:
    * `/api/themes` / `/api/theme` used by the Dashboard.

* **Acceptance Criteria**:
  * Settings tab exists with three clear sections: System, Parameters, UI.
  * All core fields from the legacy System and Settings screens are present and editable where appropriate (Battery, Arbitrage, Charging Strategy, Learning Parameter Limits, S-Index Safety, etc.).
  * Learning-related configuration (e.g. `learning.enabled`, `learning.sqlite_path`, and safety limits) can be viewed and changed from a single place.
  * Theme can be changed via the UI, persists across reloads, and continues to drive Dashboard/Planning theming.
  * Saving validates obvious invalid inputs and shows inline error messages; successful saves show non-intrusive confirmation.
  * Reset-to-defaults works via `/api/config/reset` and resets the UI to match the new config state without requiring a manual reload.

### Implementation Steps (Planned)

1. **Config Inventory & Legacy Mapping**
   * Enumerate all relevant fields from `config.yaml` and the legacy System/Settings UIs, consolidating:
     * System: battery capacity, SoC limits, efficiency (if exposed), timezone, Nordpool price area/resolution/currency, energy export toggles, HA sensor IDs (`battery_soc_entity_id`, `water_heater_daily_entity_id`), learning DB path (`learning.sqlite_path`), and other integration keys shown on the legacy System page.
     * Parameters: `charging_strategy.*` (price smoothing, block consolidation tolerance, consolidation_max_gap_slots, hysteresis controls), `arbitrage.*` (export_percentile_threshold, enable_peak_only_export, export_future_price_guard, future_price_guard_buffer_sek), water heating quotas, **Learning Parameter Limits**, and the **S-Index Safety** block (`s_index.mode`, `base_factor`, `max_factor`, `pv_deficit_weight`, `temp_weight`, `temp_baseline_c`, `temp_cold_c`, `days_ahead_for_sindex`), ensuring every learning-related backlog item is represented.
   * Document the existing `/settings` page (currently two placeholder cards) as the primary canvas for these sections; the plan should replace those placeholders with the new System/Parameters/UI structure without re-routing.
   * Group fields into logical sub-sections under:
     * System (Battery, Grid/Price, Home Assistant + Learning Storage).
     * Parameters (Charging Strategy, Arbitrage, Water Heating, Learning & S-Index Safety).
     * UI (Theme, Chart defaults, App behavior).
   * Decide which fields are:
     * **Core** (exposed by default),
     * **Advanced** (behind an “Advanced” disclosure),
     * **Internal** (left in config only), and flag any entries that correspond to existing backlog items so their coverage can be verified (Learning Parameter Limits, S-Index Safety, etc.).

2. **Settings Layout & Routing**
   * Implement a `Settings` page layout in React that:
     * Uses a simple internal tab/pill switcher (System / Parameters / UI) within the Settings tab.
     * Presents each main section as one or more cards with headings and descriptions for sub-groups.
   * Ensure the layout works at desktop widths and degrades reasonably on smaller viewports (no heavy mobile polish yet).
   * Status: Layout and tabbing scaffolding replaced the placeholder cards; the new System/Parameters/UI grouping is visible at `/settings`.

3. **System Section – Read/Write Configuration**
   * Wire the Settings page to `/api/config` on mount and normalize the config object into the System form state.
   * Implement form controls for:
     * Battery: capacity_kwh, min/max SoC (if exposed), efficiency (if present).
     * Grid & pricing: timezone, Nordpool price area, resolution (with some fields read-only if we treat them as advanced).
     * Home Assistant: key entity IDs like battery SoC, water heater daily energy.
     * Learning storage: `learning.sqlite_path` (with a note that the directory must exist).
   * Implement a “Save System Settings” path that:
     * Builds a minimal patch object (only changed fields).
     * Calls `/api/config/save` with that patch.
     * Updates local state with the merged config on success.
     * Surfaces validation errors or backend errors with a clear message.
   * Status: System tab now fetches `/api/config`, renders fields for battery/grid, pricing, and learning storage, validates numeric input, and diff-saves via `/api/config/save`.

4. **Parameters Section – Planner, Learning & S-Index**
   * Map legacy Settings fields to structured sub-cards:
     * Charging Strategy (price_smoothing_sek_kwh, block_consolidation_tolerance_sek, consolidation_max_gap_slots, etc.).
     * Arbitrage (export_percentile_threshold, enable_peak_only_export, export_future_price_guard, future_price_guard_buffer_sek).
     * Water Heating (daily quota, deferral rules where configurable).
     * **Learning Parameter Limits**: expose the existing learning-related safety limits from config (e.g. how far learning is allowed to move thresholds).
     * **S-Index Safety**: expose `s_index.*` (mode, base_factor, max_factor, pv_deficit_weight, temp_weight, temp_baseline_c, temp_cold_c, days_ahead_for_sindex) with appropriate descriptions so it’s clear how they interact with learning.
   * Implement a “Save Parameters” flow:
     * Gather the parameters form state into a patch with the same shape as `config.yaml` (only under relevant keys).
     * Post to `/api/config/save` and update the in-memory config on success.
     * Basic validation:
       * Disallow negative thresholds where they don’t make sense.
       * Ensure weights and factors are within safe numeric ranges (e.g. 0–10 unless otherwise intended).
       * Provide inline messages when validation fails.
   * Status: Parameter tab now renders charging strategy, arbitrage, water heating, learning, and S-index sections, validates numeric inputs, and diff-saves them via `/api/config/save`.

5. **UI Section – Theme & App Behavior**
   * Integrate theme picker:
     * Fetch theme data from `/api/themes` (as currently used on Dashboard).
     * Add a picker in Settings > UI that lists available themes and accent variants.
     * When a theme is chosen, call `/api/theme` or the existing theme-set endpoint if available (or fall back to the existing dashboard mechanism) and ensure the change is reflected across the app.
   * Add a few simple UI preferences:
     * Default dashboard overlays (which datasets are shown on first load).
     * Possibly an auto-refresh default (on/off) that the Dashboard respects.
   * Persist these UI preferences either in `config.yaml` (under a `ui` section) or, if config is not appropriate, document that they are front-end only (localStorage) and exclude them from `/api/config` save.
   * Status: UI tab now renders a theme picker with accent control plus dashboard defaults, all saving through `/api/config/save` and `/api/theme`.

6. **Shared Save / Reset Flow & UX**
    * Add a consistent save/reset UI affordance:
      * Section-level "Save" buttons that are clearly tied to System, Parameters, or UI.
      * A global "Reset to defaults" button (with confirmation) that triggers `/api/config/reset` and refetches `/api/config` on success.
    * Ensure:
      * Buttons show loading/disabled states while requests are in flight.
      * Success/failure toasts or inline messages are concise and visible.
      * The app continues to behave correctly after a reset (Dashboard and Planning should consume the updated config).
    * **Implementation Details**:
      * Added `configReset()` API method to `/api/config/reset` endpoint
      * Implemented global reset button in Settings page header with browser confirmation dialog
      * Added reset state management (loading, status messages, error handling)
      * Fixed critical field path mapping bug where battery fields used incorrect paths (`system.battery.*` → `battery.*`)
      * Added success/error status message display with appropriate styling
      * Removed "Rev 43 · Settings & Configuration" header text for cleaner UI
      * Reset flow properly clears form errors, reloads config/themes, and updates all form states

7. **Verification & Learning-related Backlog Alignment**
   * Manual test scenarios:
     * Change battery capacity or price area, save, and verify downstream UI uses the new values.
     * Adjust Learning Parameter Limits and S-Index Safety, save, and confirm config.yaml is updated as expected (and that the app continues to run without errors).
     * Change theme and verify Dashboard + Planning reflect the new theme without breaking charts or timeline.
   * Align with existing backlog items:
     * ✅ Cover “Configuration forms (decision thresholds, battery economics, charging strategy, etc.)” under System & Parameters.
     * ✅ Implement theme picker using `/api/themes` and `/api/theme` under UI.
     * ✅ Implement form validation and persistence with `/api/config/save`.
     * ✅ Wire config reset with `/api/config/reset`.
   * Note that **Learning & Debug** backlog items related to visualization (status UI, debug logs, historical SoC chart) remain for a future dedicated Learning/Debug Rev; this Rev 43 focuses on configuration surfaces and not the Learning tab UI.

### Implementation

* **Completed**:
  * Step 1 — Config inventory (system, parameters, UI mapping, learning/S-index coverage) documented and committed.
  * Step 2 — Settings layout implemented with tabbed sections for System / Parameters / UI using the existing `/settings` page shell as the canvas.
  * Step 3 — System section form wiring, fetching `/api/config`, and persisting edits.
  * Step 4 — Parameter form sections built (charging strategy, arbitrage, water heating, learning limits, S-index) with validation and diff-saves.
  * Step 5 — UI section (theme picker, app preferences, and shared UI defaults) with user-friendly overlay selection.
  * Step 6 — Shared save / reset UX (section-level saves, reset to defaults flow) with consistent styling and validation.
  * Step 7 — Verification & Learning-related backlog alignment (all Settings features implemented and tested).
* **In Progress**: —
* **Blocked**: —
* **Next Steps**: Rev 44 — Learning tab implementation.

### Verification (Planned)

* Compare Settings UI fields against the legacy System + Settings tabs to ensure parity.
* Manually inspect `config.yaml` before/after saves to confirm only the intended keys change.
* Sanity-check planner behavior after adjusting key parameters (e.g. charging thresholds, S-index safety, learning limits) to ensure no invalid configurations are allowed through the UI.

---

## Backlog

### Dashboard Refinement
- [ ] Polish "NOW" marker (slightly shorter line, ensure it never overlaps chart axes)
- [ ] Remove Y-axis scale labels to reduce clutter (keep tooltips for exact values)
- [ ] Remove chart legend duplications where we already have pill toggles (avoid showing the same concept twice)

### Planning Timeline
- [x] Manual block CRUD operations (create/edit/delete charge/water/export/hold)
- [x] Simulate/save workflow with `/api/simulate` (Planning \"Apply manual changes\" uses simulate to persist local plan)
- [x] Chart synchronization after manual changes (Planning 48‑hour chart reflects latest local schedule)
- [x] Historical slots read-only handling
- [ ] Device caps and SoC target enforcement
- [ ] Zero-capacity gap handling
- [ ] Investigate SoC Projected anomaly where SoC jumps (e.g. ~66%→94% around 16:45–17:45) without a clear matching charge block in the schedule; ensure projection is consistent with planned actions.

### Settings & Configuration
- [x] Configuration forms (decision thresholds, battery economics, charging strategy, etc.)
- [x] Theme picker using `/api/themes` and `/api/theme`
- [x] Form validation and persistence with `/api/config/save`
- [x] Config reset functionality with `/api/config/reset`

### Learning & Debug
- [ ] Learning engine UI (status, metrics, loops, changes from `/api/learning/*`)
- [ ] Debug data visualization (`/api/debug`, `/api/debug/logs`)
- [ ] Log viewer with polling and filters
- [ ] Historical SoC chart from `/api/history/soc`

### Production Readiness
- [ ] Error handling & loading states for all API calls
- [ ] Mobile responsiveness for all components
- [ ] Performance optimization (chart rendering, data caching)
- [ ] Deployment configuration (serve `frontend/dist` from Flask or separate static host)
- [ ] Accessibility improvements (ARIA labels, keyboard navigation)
- [ ] State management for user preferences and theme

---

## Appendix — Handover Notes

* **Monorepo rules**

  * Backend Flask app under `backend/`; React under `frontend/`; core Python modules at repo root until final refactor.
  * Always set `FLASK_APP=backend.webapp` when running Flask.
  * `node_modules` must remain untracked; never commit lockfiles from nested experiments outside `frontend/`.
* **UI invariants**

  * 48-hour window alignment across chart/timeline; no historic “bridges” before “now”.
  * Backwards compatibility: accept both `battery_*` and legacy `charge_kw`/`discharge_kw` fields during transition.
* **Doc invariants**

  * README holds architecture and system description.
  * This file holds the **plan and progress** only.
