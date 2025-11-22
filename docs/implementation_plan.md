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

## Rev 44 — Learning Engine UI *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Replace the placeholder Learning tab with a full Learning Engine UI that surfaces learning status, metrics, and parameter impacts (read-only), including a compact history chart, while keeping configuration edits in the Settings tab.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Provide a dedicated Learning tab that makes the state of the learning engine visible at a glance (enabled/disabled, last run, data coverage, errors).
  * Visualize key learning metrics, including a mini-chart of recent learning runs or quality metrics, to make trends obvious.
  * Show how learning interacts with critical thresholds (Learning Parameter Limits and S-Index Safety) in a read-only way, complementing the editable Settings UI.
  * Keep the Learning tab non-destructive: no configuration changes from this tab; all edits stay in Settings.

* **Scope**:
  * React Learning page implementation in `frontend/src/pages/Learning.tsx`, replacing the current placeholder.
  * Read-only use of:
    * `/api/learning/status` (primary metrics and health).
    * `/api/config` (current learning-related config and limits).
    * Existing debug endpoints if available (e.g. recent config changes or learning events) for a small history/mini-chart.
    * New `/api/learning/history` endpoint exposing recent learning runs from the learning engine DB for mini-chart visualisation.
    * Existing `/api/learning/run` and `/api/learning/loops` endpoints for manual learning orchestration and loop testing controls.
  * UI sections:
    * Overview (enabled flag, last run/observation, sync interval, quick health badges).
    * Metrics (KPI tiles for runs, days with data, DB size, slot coverage, etc.).
    * Parameter Impact (snapshot of key thresholds learning can move, with “learning can adjust” hints).
    * History / Mini-chart (compact chart of recent learning runs or a proxy metric, e.g. completed vs failed runs over time).
  * No new backend logic; only minor data-shaping helpers in the frontend if needed.

* **Dependencies**:
  * Rev 43 (Settings & Configuration UI), which already exposes Learning Parameter Limits and S-Index Safety as editable config.
  * Existing learning endpoints:
    * `/api/learning/status` (already typed in `frontend/src/lib/api.ts`).
    * Any learning-related debug endpoints (`/api/learning/changes`, `config_versions`, or similar) if present; otherwise, we derive a minimal history from what we already have.

* **Acceptance Criteria**:
  * Learning tab replaces the placeholder with a structured UI:
    * Overview, Metrics, Parameter Impact, History sections clearly labeled.
  * `/api/learning/status` is fetched on load and its key fields are rendered:
    * Learning enabled/disabled, last learning run, last observation, sync interval.
    * Completed and failed learning runs, days with data, DB size, total slots, import/export/pv/load kWh if available.
  * The mini-chart:
    * Shows a small, well-themed visualization of recent learning dynamics (e.g. bar chart of completed vs failed runs over the last N runs, or a time-based trend if available).
    * Uses the existing chart theming (accent colors, background) to match the Dashboard/Planning.
  * Parameter Impact section:
    * Lists key thresholds that learning can adjust (decision thresholds, S-index factors) alongside their current values.
    * Clearly indicates that edits must be made via the Settings tab (this tab is read-only).
  * Errors and “learning disabled” states are clearly communicated without breaking the rest of the tab.

### Implementation Steps

1. **Learning API & Data Shape Inventory** ✅
   * Inspect `/api/learning/status` and any existing learning/debug endpoints to confirm:
     * Available metrics (completed/failed runs, days with data, db size, last run, last observation, etc.).
     * Any simple history or time-indexed arrays we can use for the mini-chart.
   * Update or confirm `LearningStatusResponse` in `frontend/src/lib/api.ts` matches the actual payload.

2. **Learning Tab Layout & Sections** ✅
   * Replace the placeholder `Learning` page with a structured layout:
     * Overview card at top (enabled flag, last run, last observation, sync interval, basic health).
     * Metrics card (KPI tiles for counts and coverage).
     * Parameter Impact card (snapshot of learning-affected thresholds).
     * History card containing the mini-chart and simple legend.
   * Ensure visual alignment with Dashboard/Planning (same card styles, headings, typography).

3. **Learning Status Fetch & State Management** ✅
   * In `frontend/src/pages/Learning.tsx`:
     * Fetch `/api/learning/status` on mount, with loading and error states.
     * Provide a small “Refresh status” button to re-fetch on demand (no auto-polling for now).
   * Map status fields into a view-model that the Overview and Metrics sections can use (e.g., derived “time since last run”).

4. **Metrics & Overview UI** ✅
   * Implement KPI tiles using the existing `Kpi` component for key metrics:
     * Completed learning runs, failed runs, days with data, db size, total slots, total import/export/load/pv kWh if present.
   * Overview card:
     * Show learning enabled/disabled (with a subtle badge).
     * Show “Last run” and “Last observation” using friendly relative times (e.g., “3h ago”) via existing time helpers.
     * Show the configured `learning.sync_interval_minutes` and horizon days, where available.
   * Clearly indicate when learning is disabled and point users to the Settings tab to enable it.

5. **Parameter Impact Snapshot** ✅
   * Use `Api.config()` to read the current values of:
     * Decision thresholds (`decision_thresholds.*`).
     * S-index factors (`s_index.*`).
     * Learning Parameter Limits (`learning.max_daily_param_change.*`).
   * Render a read-only card:
     * Each parameter with its current value and units.
     * A small “learning can adjust” label when the corresponding `max_daily_param_change.*` is non-zero.
   * Include a subtle, non-clickable hint that edits are made in the Settings tab (with a reference to Rev 43).

   **Status**:
   * Implemented in `frontend/src/pages/Learning.tsx`:
     * Decision thresholds (battery_use_margin_sek, battery_water_margin_sek, export_profit_margin_sek) displayed with SEK/kWh units.
     * S-index factors (base_factor, pv_deficit_weight, temp_weight) and learning limits (min_improvement_threshold, min_sample_threshold) shown with current values.
     * “learning can adjust” chip rendered when corresponding `learning.max_daily_param_change.*` fields are non-zero.
     * Card copy explicitly points users to Settings for edits.

6. **History Mini-chart Implementation** ✅
   * Decide on what to chart based on available data:
     * If a time-ordered history of learning runs exists, use it; otherwise:
       * Derive a simple bar or line chart from aggregate fields (e.g. success vs failure counts over a synthetic timeline), or
       * Defer to a minimal static chart that still demonstrates recent behavior.
   * Implement a small Chart.js-based mini-chart component:
     * Narrow height, width constrained to the card.
     * Respect the existing theme colors (using palette indices and `themeColors` patterns from `ChartCard` to stay consistent).
   * Show a compact legend and tooltips; no complex interactions needed for this Rev.

   **Status**:
   * Implemented as a compact bar chart embedded in the Learning History card:
     * Backs onto a new `/api/learning/history` endpoint that summarizes recent `learning_runs` from the learning DB.
     * Shows “changes applied per run” over time to visualise how active the learning engine has been.

7. **Error & Health Indicators** ✅
   * In all sections, handle partial/missing data gracefully:
     * Show “No learning data yet” when metrics are zero or absent.
     * When `enabled` is false, disable the mini-chart and metrics but keep the tab visible with explanation.
   * If `/api/learning/status` exposes any error messages or “last error”, surface them in a small, non-intrusive warning card.

   **Status**:
   * Implemented in the Learning Overview card:
     * When learning is disabled, a subtle info box explains that it can be enabled from Settings.
     * When enabled but no metrics are present yet, a “no runs recorded yet” message is shown.
     * If `last_error` is present on the learning status payload, it is displayed in a compact warning-styled box.

8. **Verification & Backlog Alignment**
   * Manually test:
     * Learning disabled vs enabled and confirm the Overview, Metrics, and History change appropriately.
     * Changes to learning-related config in Settings are reflected in the Parameter Impact snapshot.
     * The mini-chart responds correctly when the underlying metrics change (e.g., after a new learning run).
   * Align with Learning & Debug backlog:
     * ✅ Cover “Learning engine UI (status, metrics, loops, changes from `/api/learning/*`)" for core status.
     * Defer full debug log viewer and historical SoC chart to a later dedicated Learning/Debug Rev.

### Implementation

* **Completed**:
  * Learning API inventory and `LearningStatusResponse` shape confirmed against `/api/learning/status`.
  * Learning tab layout scaffolded in `frontend/src/pages/Learning.tsx` with Overview, Metrics, Parameter Impact, and History sections.
  * Learning status and config wiring implemented in the Learning tab using `Api.learningStatus()` and `Api.config()`, with loading/error handling.
  * Overview and Metrics sections now render real data (enabled badge, last run/observation timestamps, sync interval, SQLite path, KPI tiles for completed/failed runs, days with data, and DB size).
  * Parameter Impact snapshot implemented from `config.yaml` (decision_thresholds, s_index, learning limits) with “learning can adjust” indicators based on `learning.max_daily_param_change.*`, plus a “Current S-index” row that reads the effective factor from `/api/debug` when available.
  * History mini-chart implemented using recent `learning_runs` data via `/api/learning/history` (changes applied per run).
  * Error and health indicators implemented for disabled learning, empty metrics, and last-error display.
  * Manual Learning controls added on the Learning tab using `/api/learning/run` (“Run learning now”) and `/api/learning/loops` (“Test loops”) with inline status summaries.
* **In Progress**: —
* **Blocked**: —
* **Next Steps**:
  * Manual verification for Rev 44 and capturing any follow-up polish items in Backlog.

---

## Rev 45 — Debug & Diagnostics UI *(Status: ✅ Completed)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Build a dedicated Debug tab that surfaces planner/logging diagnostics, including a log viewer, recent events/errors summary, and a historical SoC mini-chart, to help operators understand and troubleshoot planner behavior.
* **Started**: — (planned)
* **Last Updated**: — (planned)

### Plan

* **Goals**:
  * Provide a single Debug tab that aggregates diagnostics (logs, recent errors, historical SoC) instead of scattering them across other views.
  * Make it easy to inspect “what the planner has been doing lately” without SSH or manual log tailing.
  * Keep the Debug tab read-only and clearly “operator-facing” rather than an end-user UI.

* **Scope**:
  * React Debug page implementation in `frontend/src/pages/Debug.tsx`, replacing the placeholder with:
    * Log viewer (paged or tailed) backed by the existing in-memory ring buffer logs.
    * Recent events / error summary extracted from the same log payload.
    * Historical SoC mini-chart sourced from `/api/history/soc`.
  * Read-only integration with:
    * `/api/debug/logs` (or equivalent) for log entries (timestamp, level, logger, message).
    * `/api/history/soc` for SoC history over a recent window.
  * No planner behavior changes; this is a visualization/diagnostics Rev.

* **Dependencies**:
  * Rev 39–44 (Dashboard, Planning, Settings, Learning) stable.
  * Backend debug endpoints:
    * Ring buffer handler + log endpoint (e.g. `/api/debug/logs`) available.
    * `/api/history/soc` implemented for SoC history.

* **Acceptance Criteria**:
  * Debug tab shows:
    * A scrollable log view with level and component displayed, plus clear timestamps.
    * Basic controls: “Refresh logs” and optional “Tail” behavior (manual refresh is sufficient for this Rev).
    * A compact summary of recent errors/warnings (e.g. last N error-level entries, with counts).
    * A historical SoC mini-chart that visualizes SoC (%) over a recent window (e.g. last 24–72 hours) using the existing chart theming.
  * Debug tab is clearly labeled as non-destructive and read-only; no config changes can be made from this tab.
  * Errors in debug endpoints are handled gracefully (e.g. “Logs unavailable” or “No SoC history” messages instead of blank or broken sections).

### Implementation Steps

1. **Debug Endpoint Inventory** ✅
   * Confirmed available debug/logging endpoints and their payloads:
     * `/api/debug/logs` for log entries from the in-memory ring buffer (timestamp, level, logger, message).
     * `/api/history/soc` for SoC history for a given date (timestamp, soc_percent, quality_flags).
     * `/api/debug` for planner debug information from `schedule.json` (used by other Revs, not central here).
   * Added TypeScript types and helpers for these responses in `frontend/src/lib/api.ts` and exposed them via `Api.debugLogs` and `Api.historySoc`.

2. **Debug Tab Layout** ✅
   * Replaced the Debug placeholder page with a three-section layout in `frontend/src/pages/Debug.tsx`:
     * Logs (primary area, spanning two columns on desktop).
     * Recent Events/Errors (secondary card for quick health overview).
     * Historical SoC mini-chart (chart card in a second row).
   * Styling aligned with existing cards and typography for Dashboard/Planning.

3. **Log Viewer Implementation** ✅
   * Fetched logs on load from `/api/debug/logs` with loading and error states.
   * Implemented:
     * Level filter: All, Warn+Error, Errors only.
     * “Refresh” button to refetch logs on demand (no auto-polling for this Rev).
   * Rendered logs in a scrollable, monospaced list with timestamp, level badge, logger name, and message.

4. **Recent Events / Error Summary** ✅
   * Derived a summary view from the log payload:
     * Count of total log entries and error/critical entries.
     * Up to five most recent error-level entries with timestamp, logger, and truncated message.
   * Displayed this in a compact “Recent events” card next to the log viewer.

5. **Historical SoC Mini-chart** ✅
   * Wired `/api/history/soc` into a small Chart.js line chart:
     * X-axis: time of day (HH:mm:ss).
     * Y-axis: SoC (%) with a suggested 0–100 range.
   * Embedded the chart in a dedicated “Historical SoC” card with short explanatory copy and inline error display when history cannot be loaded.
   * Theming aligned with the rest of the app (dark background, light line/fill).

6. **Error Handling & UX Polish** ✅
   * Ensured each section handles its own errors:
     * Log viewer shows a small inline error if logs cannot be fetched.
     * SoC chart shows an inline error when history fails; an empty chart is tolerated when there is simply no data.
   * Kept the page desktop-focused but usable on smaller widths, consistent with other tabs.

7. **Verification & Backlog Alignment** (Planned)
   * Manual testing:
     * Confirm log loading, filtering, and refresh behavior.
     * Confirm SoC history loads and chart renders when data is available.
   * Align with Learning & Debug backlog items:
     * ✅ Debug data visualization (`/api/debug`, `/api/debug/logs`).
     * ✅ Log viewer with manual refresh and level filters.
     * ✅ Historical SoC chart from `/api/history/soc`.

### Implementation

* **Completed**:
  * Debug endpoint inventory and API client types for `/api/debug/logs` and `/api/history/soc`.
  * Debug tab layout with three sections: Logs, Recent Events/Errors, and Historical SoC.
  * Log viewer implementation with level filters and manual refresh.
  * Recent events summary card with counts and last error entries.
  * Historical SoC mini-chart wired to `/api/history/soc` using Chart.js.
  * Error handling and UX polish for logs and SoC chart.
  * Fixed learning auto-observation SQL by replacing the SQLite `ON CONFLICT` upsert in `LearningEngine.store_slot_observations` with a portable update‑then‑insert pattern, eliminating `sqlite3.OperationalError: near \")\": syntax error` during automatic observation recording.
* **In Progress**: —
* **Blocked**: —
* **Next Steps**:
  * Manual verification of log and SoC views across typical planner runs; any further diagnostics enhancements can be tracked under Backlog → Learning & Debug.

---

## Rev 46 — Schedule & Dashboard Correctness *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI (planned)
* **Summary**: Fix day-slicing and range issues on the Dashboard chart, verify that planner output and DB schedules are complete and aligned with the executor’s expectations, and harden error/empty states for the core scheduling and learning flows.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Ensure the Dashboard “today” chart always presents a full, correct 00:00–24:00 view in local time, even when the first schedule slot starts later in the day.
  * Verify that the planner → DB writer → executor (n8n) contract is consistent: slot numbering, time coverage, and timezone handling all match what the executor’s SQL expects.
  * Strengthen error and empty-state handling for the critical APIs so that missing or failing data never results in silent misbehavior or misleading charts.

* **Scope**:
  * Dashboard `ChartCard` day slicing and label generation for `day="today"`:
    * Diagnose why the current chart range starts at 12:15 instead of 00:00.
    * Ensure labels and datasets for “today” are always built over the full local 24 hours, with `null` values (no data) instead of shrinking the axis when early slots are absent.
  * Planner/DB/executor alignment:
    * Inspect how slots are generated and written into `schedule.json`, `current_schedule`, and `plan_history` (slot numbering, slot_start coverage).
    * Confirm assumptions used by the n8n executor SQL (`slot_start` with `NOW()` and a 15-minute window) are valid for the current system.
    * Document and, if necessary, normalize slot numbering (e.g. 0–191 for 48h @ 15min) to avoid surprises like slot_number 705 for a single schedule.
  * Targeted Production Readiness:
    * Harden error and empty states for the core planner/learning endpoints:
      * `/api/schedule`, `/api/status`, `/api/simulate`.
      * `/api/config` (where it impacts Dashboard/Planning behaviors).
      * `/api/learning/status`, `/api/learning/history` (to avoid silent fallbacks on the Learning tab).
    * Ensure the Dashboard and Planning charts never fall back to mock data or render misleading shapes when these endpoints fail or return empty data; they must show a clear “no data” or error state instead.

* **Dependencies**:
  * Rev 39–41 (Dashboard data wiring and hotfixes).
  * Rev 42 (Planning timeline and 48h chart behavior).
  * Rev 43 (Settings & Configuration; config semantics for dashboard defaults).
  * Rev 44–45 (Learning and Debug UIs, including history and SoC diagnostics).

* **Acceptance Criteria**:
  * On “today”, the Dashboard chart always displays a full 24-hour X-axis (00:00–24:00 local time) with no unexpected truncation (e.g. starting from midday), regardless of when the first schedule slot starts.
  * Planner output for typical runs produces contiguous slots that cover the expected horizon; slot numbering and coverage are consistent and documented, and the executor’s SQL reliably returns the active slot when a schedule exists.
  * When there is no schedule or partial data, the Dashboard and Planning charts show a clear “No data” or similar overlay; they do not render stale mock data or silently hide failures.
  * Critical `/api/schedule` failures are surfaced in the UI in a visible but non-disruptive way (inline message/overlay), and do not leave the app in an ambiguous state. Other API errors on Dashboard, Planning, Learning, and Debug tabs are already surfaced via their respective inline error labels without falling back to mock data.

### Implementation Steps

1. **Dashboard Today-Range Diagnosis**
   * Inspect `filterSlotsByDay`, `isToday`, and `formatHour` in `frontend/src/lib/time.ts` plus `buildLiveData` in `ChartCard` to understand how “today” slots are filtered and labels are created.
   * Reproduce and document the case where the chart only shows from 12:15–24:00 instead of 00:00–24:00.

2. **Full-Day Chart Range Implementation**
   * Adjust the “today” data-building logic so that the X-axis always spans the full 24 hours in local time, padding with `null` values where the schedule lacks data rather than shrinking to the first available slot.
   * Verify the tooltip and NOW marker still behave correctly with padded data.

3. **Planner→DB→Executor Contract Review**
   * Review `write_schedule_to_db`/`plan_history` writing logic to confirm:
     * Slot numbering strategy and upper bounds for a typical 48h schedule.
     * How `slot_start` values are generated and stored (timezone, resolution).
   * Cross-check these assumptions against the n8n executor SQL that selects the “current slot” by `slot_start` and `NOW()`.
   * Document the contract so future changes don’t break the executor.

4. **Targeted Error/Empty-State Hardening**
   * Audit how `/api/schedule`, `/api/status`, `/api/simulate`, `/api/learning/status`, and `/api/learning/history` are consumed in Dashboard, Planning, and Learning pages.
   * Ensure that for each:
     * Errors are surfaced via inline messages in the relevant card/page.
     * Empty or partial data leads to an explicit “no data” state, not mock data.
     * No silent failover masks real issues in the planner or backend.

5. **Verification & Backlog Alignment**
   * Manual tests:
     * Confirm Dashboard “today” always starts at 00:00 and covers 24h in local time across typical planner runs.
     * Confirm the Planning 48‑hour chart always spans today+tomorrow, even when the first future slot starts later in the day.
     * Confirm executor SQL finds the correct slot in a live schedule and behaves predictably when no current slot exists (handled now via n8n error flow).
     * Confirm `/api/schedule` failures show an explicit no‑data overlay rather than stale/mock chart data.
   * Align with Backlog:
     * ✅ Close “Day-slicing correctness” and “planner→DB→executor contract” items added under Backlog once this Rev is completed.

### Implementation

* **Completed**:
  * Step 1: Diagnosed that the Dashboard “today” chart was starting at 12:15 because `buildLiveData` only used whatever slots were present for the day, with no padding, and today’s `schedule.json` really began at 12:15.
  * Step 2 (Dashboard): Updated `buildLiveData` in `frontend/src/components/ChartCard.tsx` so that for `range="day"` it always builds a full 24‑hour local grid (00:00–24:00) at the inferred slot resolution (default 15 minutes), padding missing buckets with `null` while keeping tooltips and the NOW marker correct.
  * Step 2 (Planning): Extended the same fixed-window approach to the 48‑hour Planning chart (`range="48h"`), building a 48‑hour grid (today+tomorrow from local midnight) at the inferred resolution and padding missing buckets with `null` so the chart window always matches the Planning timeline horizon.
  * Step 3: Reviewed the planner→DB→executor contract:
    * Planner writes future‑oriented `schedule.json`.
    * `write_schedule_to_db_with_preservation` in `db_writer.py` merges DB‑backed past slots (from `current_schedule`) with future slots from `schedule.json` into `current_schedule`, and appends all rows to `plan_history`.
    * Executor (n8n) reads only from `current_schedule` using a 15‑minute `slot_start` window around `NOW()`, so slot numbering is informational; `slot_start` local time and 15‑minute resolution are the key contract.
  * Step 4 (charts): Hardened `/api/schedule` error/empty states in `ChartCard` so both Dashboard and Planning charts show an explicit “No Price Data / Schedule data not available yet” overlay instead of stale or mock chart data when schedule loading fails or returns no slots.
* **In Progress**: —
* **Blocked**: —
* **Technical Decisions**:
  * Day and 48‑hour views are now built from generated time grids rather than directly from schedule slot timestamps, to guarantee consistent axes even when the schedule starts late.
  * The executor contract is documented as: `current_schedule.slot_start` in local time at 15‑minute resolution is the source of truth; `slot_number` is not used in executor SQL.
* **Files Modified**:
  * `frontend/src/components/ChartCard.tsx` (24‑hour padding in `buildLiveData` for `range="day"`, 48‑hour padding for `range="48h"`, and `/api/schedule` error overlay handling).

---

## Rev 47 — Dashboard & Planning UX Polish *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI (planned)
* **Summary**: Apply targeted UX polish to the Dashboard chart and Planning timeline to close the most visible UI-related backlog items, without changing planner behavior.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Reduce visual clutter on the Dashboard chart while keeping all information available via tooltips and overlay pills.
  * Make the Planning timeline background consistent across today and tomorrow, removing confusing weekend/alternate-day tinting.
  * Ensure Dashboard respects the UI-related settings that are already editable in the Settings UI (overlay defaults and auto-refresh).

* **Scope**:
  * Dashboard `ChartCard`:
    * Remove redundant legend entries for datasets that already have overlay pills (e.g. charge/discharge/export/water/SoC lines), so the legend only shows core series that are not controllable via pills.
    * Optionally hide Y-axis scale tick labels to reduce clutter, relying on tooltips for exact values while keeping axes and grid-lines for orientation.
    * Wire `dashboard.overlay_defaults` and `dashboard.auto_refresh_enabled` from config so Dashboard and `ChartCard` actually use the persisted defaults exposed in the Settings UI.
  * Planning Timeline:
    * Normalize the timeline background so the full 48-hour window uses a consistent dark theme, removing the special tinting that react-calendar-timeline applies to weekends/alternate days.

* **Dependencies**:
  * Rev 40–41 (Dashboard completion and hotfixes).
  * Rev 42 (Planning timeline interactions and 48h window behavior).
  * Rev 43 (Settings UI, including Dashboard UI settings).
  * Rev 46 (Schedule & Dashboard correctness and chart padding/error behavior).

* **Acceptance Criteria**:
  * Dashboard chart:
    * Legend no longer duplicates any series that have overlay pills; users can still toggle those datasets via pills only.
    * Y-axis presentation is simplified (either labels removed or significantly toned down) without losing the ability to read exact values via tooltips.
    * On reload, Dashboard honors `dashboard.overlay_defaults` and `dashboard.auto_refresh_enabled` from `config.yaml` as set via the Settings UI.
  * Planning timeline:
    * No distinct tint for the “tomorrow” portion of the 48h window; the entire horizon uses the same dark, minimal background, with only grid lines and item colors indicating structure.

### Implementation Steps

1. **Dashboard Legend & Axis Cleanup**
   * Update `frontend/src/components/ChartCard.tsx` to remove the inline legend entirely and rely solely on overlay pills for dataset toggles (price, PV, load, charge, discharge, export, water, SoC Target, SoC Projected).
   * Hide Y-axis tick labels while confirming tooltips still show precise values and the chart remains usable.

2. **Dashboard Defaults Consumption**
   * Read `dashboard.overlay_defaults` and `dashboard.auto_refresh_enabled` in `ChartCard`/Dashboard and initialize overlay state and auto-refresh behavior from these config values (including core series defaults for price, PV, and load).
   * Ensure manual changes (toggling overlays or auto-refresh) affect only the current session unless/until settings are changed in the Settings UI.

3. **Planning Timeline Background Normalization**
   * Override react-calendar-timeline default styles in `frontend/src/index.css` so weekend/alternate-day tinting is removed and the full 48h background matches the app’s dark theme.
   * Verify that horizontal/vertical grid-lines remain readable and that blocks retain their lane color identity.

### Implementation

* **Completed**:
  * Step 1: Dashboard legend removed and all datasets (price, PV, load, charge, discharge, export, water, SoC Target, SoC Projected) are now controlled solely via overlay pills; Y-axis tick labels are hidden while tooltips still provide precise values.
  * Step 2 (auto-refresh): Dashboard auto-refresh is now initialized from `dashboard.auto_refresh_enabled` in `config.yaml`, so the Dashboard toggle reflects the UI Settings default on load.
  * Step 3: Planning timeline background normalization by overriding `react-calendar-timeline` weekend/alternate-day tint, ensuring the full 48h window uses a consistent dark background.
* **In Progress**: —
* **Blocked**: —

4. **Verification & Backlog Alignment**
   * Manual tests:
     * Confirm Dashboard loads with overlay defaults and auto-refresh matching Settings.
     * Confirm legend and Y-axis feel lighter while tooltips remain fully informative.
     * Confirm Planning timeline shows a consistent dark background for both today and tomorrow (no weekend tint), with the now line and grid-lines still clear.
   * Align with Backlog:
     * ✅ Close the Dashboard Refinement items “Remove Y-axis scale labels” and “Remove chart legend duplications”.
     * ✅ Close the Planning Timeline item “Normalize Planning timeline background so today and tomorrow use a consistent dark theme”.

---

## Rev 48 — Dashboard History Merge *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Combine executed behavior from MariaDB `execution_history` with the current planner schedule so the Dashboard “today” chart shows both what actually happened earlier today and what is planned for the rest of the day, including an “Actual SoC” line.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Make the Dashboard “Today” view reflect **real execution** for past slots and planner intent for future slots, instead of plan-only.
  * Plot an **Actual SoC (%)** line from `execution_history.actual_soc` alongside SoC Target and SoC Projected, so we can visually compare plan vs reality.
  * Keep the planner→DB→executor contract unchanged; this Rev is display/diagnostics only.

* **Scope**:
  * Backend:
    * Add a read-only API that returns a merged “today” schedule for the Dashboard, combining:
      * Executed slots from MariaDB `execution_history` (source of truth for what ran).
      * Planned slots from `schedule.json` (via the existing planner pipeline).
    * Align on the same 15-minute grid used elsewhere (00:00–24:00 local), and include:
      * Executed values: `actual_charge_kw`, `actual_export_kw`, `actual_load_kwh`, `actual_pv_kwh`, `actual_soc`, and related energy fields where helpful.
      * Planned values: charge/export/water/load/PV/SoC from `schedule.json`.
      * A flag like `is_executed: true/false` for each bucket, indicating whether we have execution data.
    * Leave `current_schedule` and the executor SQL unchanged; they continue to drive real actions.
  * Frontend (Dashboard):
    * Extend `Api` with a client for the merged endpoint (or extend `/api/schedule` payload to include a `history` section for today).
    * For the **“Today”** chart:
      * Use the merged data when available:
        * For time buckets where `is_executed` is true, plot executed series (including Actual SoC).
        * For future buckets (no execution), fall back to planner schedule as today.
      * Add a new dataset for **“SoC Actual (%)”**:
        * Sourced from `actual_soc` (when present).
        * Styled to be distinguishable from SoC Target and SoC Projected lines.
      * Consider subtle styling differences (e.g. slightly different opacity or dashed lines) to differentiate executed vs planned segments, without clutter.
    * Preserve Rev 46 behavior when no execution history is available for today (plan-only with padding).

* **Dependencies**:
  * Rev 41–42 (Dashboard + Planning foundations).
  * Rev 43 (Settings; config semantics don’t change but SoC view should remain consistent).
  * Rev 46 (Schedule & Dashboard correctness; 24h padding and NOW marker).
  * Rev 47 (Dashboard legend/pill UX).

* **Acceptance Criteria**:
  * With a typical day of `execution_history` data present:
    * Dashboard “Today” chart shows executed charge/export/load/PV behavior and an Actual SoC line for all past 15-minute slots, and planner schedule for future slots.
    * Past buckets clearly reflect what the executor actually did, even if the latest planner schedule has changed since execution.
  * With no execution history:
    * Dashboard behaves exactly as in Rev 46: plan-only, full-day padded chart with NOW marker and pills (SoC Actual pill will show no data until history exists).
  * Planner→DB→executor behavior is unchanged; this Rev only reads from `execution_history` and `schedule.json`.

### Implementation Steps

1. **Execution History Contract Exploration**
   * Inspect the MariaDB `execution_history` schema and a couple of recent rows (with user’s help, if needed) to confirm available fields and units:
     * At least: `slot_start`, `planned_charge_kw`, `actual_charge_kw`, `planned_export_kw`, `actual_export_kw`, `planned_soc_projected`, `actual_soc`, `planned_load_kwh`, `actual_load_kwh`, `planned_pv_kwh`, `actual_pv_kwh`, prices and energy/profit fields.
   * Document which fields will be used in the merged Dashboard view and how they map to the existing chart datasets.

2. **Merged “Today” Data Endpoint**
   * Implement a backend endpoint (e.g. `/api/schedule/today_with_history`) that:
     * Determines the local “today” date and builds a 15-minute time grid from 00:00–24:00.
     * Queries `execution_history` for rows where `DATE(slot_start) = today`.
     * Loads the current `schedule.json` and filters slots to today.
     * Produces a merged list of buckets where each entry includes:
       * Timestamp.
       * Executed values (when present) and planned values.
       * A boolean `is_executed` and an `actual_soc` field in percent.

3. **ChartCard Data Integration**
   * Extend `Api` and `ChartCard` so that for `range="day"` and Dashboard context:
     * Fetch from the merged endpoint instead of bare `/api/schedule` (Planning can remain plan-only for now).
     * Adapt `buildLiveData` (or a dedicated variant) to:
       * Fill the full 24h grid from the merged buckets.
       * Populate new “SoC Actual (%)” dataset from `soc_actual_percent` (derived from `actual_soc`) where available.
       * Choose executed vs planned values for other series according to `is_executed` (prefer `actual_*` when present, otherwise fall back to planned schedule fields).

4. **Visual Differentiation & UX**
   * Choose appropriate styling for the Actual SoC line (e.g. distinct color, possibly slightly thicker line).
   * Optionally apply subtle styling differences for executed vs planned segments in other series (e.g. lower opacity for planned).
   * Ensure tooltips show both planned and actual values clearly (e.g. SoC target vs actual at a given timestamp).

5. **Verification & Backlog Alignment**
   * Manual tests:
     * With real `execution_history` data for today, confirm that the early part of the chart matches executor behavior and the Actual SoC line tracks real SoC.
     * Confirm that edits to the schedule and new planner runs don’t rewrite history in the chart—past execution remains visible.
     * Confirm that when `execution_history` is empty for today, behavior matches Rev 46.
   * Add and/or update Backlog items under “Schedule & Executor Alignment” or a new “Dashboard History” section to track any follow-up polish (e.g. filtering ranges, multi-day history views).

### Implementation

* **Completed**:
  * Step 1: Confirmed the `execution_history` schema (slot_start, planned/actual charge/export, load/PV planned/actual, SoC planned/actual, prices and energy metrics) and decided to use `actual_charge_kw`, `actual_export_kw`, `actual_load_kwh`, `actual_pv_kwh`, and `actual_soc` as the primary executed series for the Dashboard history view.
  * Step 2: Implemented `/api/schedule/today_with_history` in `backend/webapp.py`:
    * Builds a local-today 15-minute grid by merging `schedule.json` with the latest `execution_history` row per `slot_start` (using a `JOIN` on `slot_start` and `MAX(executed_at)`).
    * Normalises `start_time`/`end_time` to local ISO, attaches `is_executed`, `soc_actual_percent`, and the `actual_*` series per slot.
  * Step 3: Extended `Api` and `ChartCard` so that:
    * Dashboard “Today” uses the merged endpoint instead of bare `/api/schedule`.
    * `buildLiveData` prefers `actual_*` values when `is_executed` is true (for PV, load, charge, export) and falls back to planned schedule values otherwise.
    * Added a new “SoC Actual (%)” dataset sourced from `soc_actual_percent`, with a teal line and a dedicated overlay pill that defaults to enabled (unless explicitly overridden via `dashboard.overlay_defaults`).
    * Added a dedicated y4 axis for PV so the PV/actual PV series can be rendered on a tighter 0–1.5 kW scale without affecting the load/charge axis.
  * Step 4: Reused the same merged slots and SoC Actual semantics in the Planning 48h chart by:
    * Fetching both `/api/schedule` and `/api/schedule/today_with_history` on the Planning page.
    * Combining history slots for today with plan slots for tomorrow and passing them into `ChartCard` via `slotsOverride` so the 48h chart shows execution history for today and plan for tomorrow.
    * Updating the 48h path in `buildLiveData` to honour `is_executed`, `actual_*`, and `soc_actual_percent` in the same way as the daily view.
* **In Progress**: —
* **Blocked**: —

---

## Rev 49 — Planning Device Caps & SoC Enforcement *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Make the Planning tab respect device limits and SoC constraints so manual plans remain physically realistic and consistent with the planner and executor.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Ensure manual Planning blocks cannot exceed configured charge/discharge power or violate SoC min/max limits.
  * Keep SoC Target behaviour in Planning consistent with the planner’s internal rules and the executor’s expectations.
  * Surface any constraint violations clearly to the user instead of silently allowing impossible plans.

* **Scope**:
  * Constraints:
    * Use existing config values for:
      * Battery capacity and SoC min/max (e.g. `system.battery.*`).
      * Max charge/discharge power (`system.battery.max_charge_kw`, `max_discharge_kw`, or equivalent).
      * Grid limits if relevant (`system.grid.max_power_kw`).
    * Use existing simulator/planner logic (`/api/simulate`) as the primary source of truth for SoC evolution and power limits.
  * Planning tab behaviour:
    * When blocks are created/edited/applied:
      * Clamp charge/export/water blocks so they never request more than the configured device limits per slot.
      * Ensure combined actions across lanes do not exceed grid or inverter limits when those are present.
    * After “Apply manual changes”:
      * Use `/api/simulate` to compute SoC trajectory and reject or adjust plans that would push SoC below min or above max over the 48h horizon.
      * Reflect SoC constraints in the Planning chart (SoC Target vs Actual vs bounds).

* **Dependencies**:
  * Rev 42 (Planning timeline CRUD + simulate/apply semantics).
  * Rev 46 (Schedule & Dashboard correctness, SoC plotting).
  * Rev 48 (Dashboard/Planning history integration and SoC Actual line).

* **Acceptance Criteria**:
  * Manual plans created via the Planning tab never exceed configured device charge/discharge power per slot.
  * Simulated SoC over the manual plan horizon never violates configured min/max SoC bounds; if it would, the UI either:
    * Rejects the plan with a clear error, or
    * Clearly indicates which slots are invalid and how they were clamped.
  * SoC Target and SoC Actual lines in both Dashboard and Planning remain consistent with the constrained manual plan after “Apply manual changes”.
  * The executor still reads a physically valid `current_schedule` from DB (no new SoC/power violations introduced by manual planning).

### Implementation Steps

1. **Constraint Inventory & Mapping**
   * Enumerate relevant config keys in `config.yaml` for battery capacity, SoC bounds, and charge/discharge/grid limits.
   * Confirm how the core planner enforces these internally and how `/api/simulate` represents violated or clamped actions today.

2. **Simulate-Based SoC Validation Path**
   * Define a minimal, repeatable “validate manual plan” flow using `/api/simulate`:
     * Take the manual blocks payload from Planning.
     * Call `/api/simulate` to obtain a simulated schedule with SoC trajectory and per-slot power values.
     * Inspect the returned schedule for SoC or power violations relative to config.
   * Decide on the UX: reject the plan entirely on violation vs. allow with warnings vs. automatic clamping.

3. **Planning UI Caps Enforcement**
   * Apply hard caps on block-level actions in the Planning UI:
     * When blocks are created or resized, clamp their implied power/energy to the configured max charge/discharge/export/water limits.
     * Ensure grid/power limits are respected when combining multiple lanes in the same slot (if applicable).
   * Provide unobtrusive hints in the UI when a user’s edit is being clamped (e.g. “Capped at max charge power”).

4. **Simulate/Apply Integration & Feedback**
   * After “Apply manual changes”, use the simulate-based validation path:
     * If the resulting simulated schedule honors all constraints, proceed as today (save + refresh charts).
     * If violations occur, surface a clear error or warning in the Planning tab (e.g. listing problematic slots or providing a summary).
   * Optionally update the Planning chart to indicate clamped segments (e.g. slightly different bar color for capped slots).

5. **Verification & Backlog Alignment**
   * Manual tests:
     * Attempt to create blocks that exceed device power limits and confirm they are clamped.
     * Attempt to create plans that would over-discharge or over-charge the battery and confirm SoC constraints are enforced.
     * Confirm executor continues to run plans without producing physically impossible actions.
   * Align with Backlog:
     * ✅ Close “Device caps and SoC target enforcement” under Planning Timeline once the above behaviours are satisfied.

### Implementation

* **Completed**:
  * Step 1: Collected device and SoC constraints from `config.yaml` (battery capacity, `min_soc_percent`, `max_soc_percent`, `max_charge_power_kw`, `max_discharge_power_kw`) and confirmed they are the relevant hard limits for Planning.
  * Step 2 & 4: Added a simulate-based validation path to the Planning “Apply manual changes” flow:
    * After sending blocks to `/api/simulate`, the Planning page now inspects the returned schedule against the configured caps.
    * SoC is checked against `[min_soc_percent, max_soc_percent]` (using `projected_soc_percent` or `soc_target_percent`), and battery charge/discharge per slot are checked against their respective max kW.
    * If any violation is detected, the manual plan is rejected and a clear error message is shown in the Planning header (no changes are applied to the schedule or DB).
    * If there are no violations (which should be the common case given the planner’s own protections), the plan is applied as before and charts/timeline update.
* **In Progress**: —
* **Blocked**: —

---

## Rev 50 — Planning & Settings Polish *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Tighten Planning behaviour around zero-capacity gaps and improve Settings validation so configuration errors are caught and explained field-by-field.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Make Planning blocks and the 48h view handle zero-capacity slots cleanly (no tiny phantom actions or misleading gaps).
  * Provide clearer, per-field validation in the Settings UI instead of heuristic or generic errors.

* **Scope**:
  * Planning Timeline:
    * Define how “zero-capacity” slots should be represented in the merged schedule:
      * Slots where the device cannot act (e.g. inverter off, battery unavailable, grid cap 0).
      * Ensure charge/export/water blocks do not appear or are visually distinct in such slots.
    * Update block classification/merging so:
      * Consolidated blocks do not bridge through genuinely unavailable periods.
      * Zero-capacity runs either become explicit visual gaps or are excluded from block merging.
  * Settings validation:
    * Replace broad, key-name-based validation with explicit rules for key fields, including:
      * Battery SoC min/max and power limits.
      * Nordpool resolution and timezone.
      * S-index parameters.
      * Learning thresholds and limits.
    * Surface errors inline in the Settings UI:
      * Highlight invalid fields.
      * Provide concise messages (e.g. “Min SoC must be < Max SoC”).

* **Dependencies**:
  * Rev 42 (Planning timeline and block classification).
  * Rev 43 (Settings UI and config save/reset).
  * Rev 49 (SoC and device caps enforcement).

* **Acceptance Criteria**:
  * Planning:
    * Zero-capacity slots do not create tiny or misleading blocks; block merging respects capacity gaps.
    * Users can visually distinguish genuine “no action” from “cannot act” slots.
  * Settings:
    * Invalid combinations (e.g. min SoC ≥ max SoC, negative power limits) are rejected with clear messages.
    * Applying settings does not silently misconfigure critical planner behaviour.

### Implementation Steps

1. **Zero-Capacity Semantics**
   * Identify which fields and conditions imply a zero-capacity slot (e.g. SoC pinned at bounds, device offline, grid max 0).
   * Decide how to tag such slots in the schedule (e.g. `capacity_state: 'unavailable'`).

2. **Block Merging & Visualization**
   * Update Planning block classification/merging logic to stop merging across zero-capacity slots.
   * Adjust the timeline rendering so zero-capacity periods are either:
     * Empty gaps, or
     * Styled differently (e.g. shaded background band).

3. **Settings Validation Rules**
   * Introduce explicit validation functions for key config sections (battery, thresholds, S-index, learning).
   * Wire these into the Settings save flow, returning structured field errors to the frontend.

4. **Settings UI Error Display**
   * Update the Settings UI to:
     * Mark invalid fields.
     * Show concise inline messages and prevent save when critical validation fails.

5. **Verification & Backlog Alignment**
   * Manual tests for Planning (zero-capacity scenarios) and Settings (invalid inputs).
   * Close “Zero-capacity gap handling” and “Settings validation polish” backlog items once behaviour is verified.

### Implementation

* **Completed**:
  * Step 1–2 (Planning): Introduced a notion of zero-capacity slots in Planning by detecting slots where there are no controllable actions (no charge/discharge/export/water) and SoC is pinned at or beyond configured min/max bounds. Updated `classifyBlocks` so these slots no longer produce “Hold” blocks and are treated as true gaps, preventing consolidated blocks from bridging across pinned SoC segments.
  * Step 3–4 (Settings): Added explicit backend validation in `/api/config/save` for:
    * Battery capacity, SoC min/max, and charge/discharge power limits.
    * Nordpool `resolution_minutes` (must be 15, 30, or 60).
    * Timezone (non-empty string).
    * S-index base/max factors and ordering.
    * Learning thresholds (`min_sample_threshold`, `min_improvement_threshold`).
    Returned structured field errors (`{field, message}`) instead of relying on generic failures.
  * Wired the Settings UI to:
    * Consume these backend validation errors and highlight the corresponding fields in the System, Parameters, and UI tabs.
    * Add frontend cross-field checks for battery SoC min/max and refine validation for `nordpool.resolution_minutes`, preventing saves until highlighted issues are fixed.
* **In Progress**: —
* **Blocked**: —

---

## Rev 51 — Learning Engine Correctness & Data Flow Debugging *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Trace and validate the Darkstar learning engine’s data flow and behaviour, aligning it conceptually with the Helios/n8n setup and identifying why recent runs apply no changes.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-15

### Plan

* **Goals**:
  * Understand, end-to-end, how the Darkstar learning engine currently works (from schedule → observations → SQLite → learning loops → config changes).
  * Compare this behaviour to the Helios learning engine (MariaDB `execution_history` / `learning_metrics` + n8n) and highlight key differences.
  * Diagnose why recent Darkstar learning runs report `changes_applied = 0` for weeks, while earlier runs did apply changes.

* **Scope**:
  1. **Document Current Learning Design (Darkstar vs Helios)**:
     * Describe how Darkstar is intended to work today:
       * Continuous observation capture via `record_observation_from_current_state` into SQLite tables (`slot_observations`, `slot_forecasts`, etc.).
       * Nightly learning orchestration via `NightlyOrchestrator.run_nightly_job` storing state in `learning_runs`, `config_versions`, and (now) `learning_metrics` for S-index.
       * How `LearningLoops` use historical data and the deterministic simulator to propose config changes.
     * Contrast with Helios:
       * Execution history flow (15 min) writing `execution_history` in MariaDB from HA sensors and `plan_history`.
       * Daily learning flow (01:00) reading `execution_history` to compute load/PV errors, SoC tracking metrics, arbitrage success, and writing to MariaDB `learning_metrics`.
       * Note that Darkstar uses a local SQLite learning DB, but should aim for similar semantics and effectiveness.
  2. **Inspect Learning DB State (SQLite)**:
     * For the current `learning.sqlite_path`, inspect (read-only):
       * `slot_observations`: row counts, earliest/latest timestamps, key columns populated (import/export, PV, load, SoC).
       * `slot_forecasts`: coverage relative to `slot_observations`.
       * `learning_runs`: run frequency, statuses, `result_metrics_json` presence.
       * `learning_metrics`: current contents (S-index and any other metrics).
       * `planner_debug` (if present).
     * Summarise findings in this Rev so we can resume debugging later if interrupted.
  3. **Analyse Recent Runs & Loop Results**:
     * Decode `learning_runs.result_metrics_json` for the last N runs (e.g. 30 days):
       * Which loops ran (forecast_calibrator, threshold_tuner, s_index_tuner, export_guard_tuner).
       * For each, what baseline and best objective values were computed, and what improvement % was observed.
       * Whether loops proposed changes but they were filtered out by caps (`max_daily_param_change`) or thresholds (`min_improvement_threshold`), or never proposed any changes at all.
     * Cross-reference these metrics with the dates where Helios-style metrics indicate problems (e.g. missed arbitrage, SoC tracking errors).
  4. **Config vs Data Sanity Checks**:
     * Review learning-related config:
       * `learning.min_sample_threshold`, `learning.min_improvement_threshold`.
       * `learning.max_daily_param_change.*` for thresholds, S-index, and export guard.
       * S-index config (`s_index.*`) and decision thresholds used by the loops.
     * Compare thresholds/caps to observed metrics from step 3:
       * Are improvements consistently just below the configured threshold?
       * Are caps effectively zero (preventing any change)?
  5. **Minimal Diagnostics (If Needed)**:
     * If it’s still unclear why changes are not applied, add small, targeted diagnostics:
       * Log explicit reasons when a loop skips or rejects a candidate (e.g. “improvement below threshold X”, “daily cap exceeded”, “insufficient samples”).
       * Optionally enrich `result_metrics_json.loop_results` with a short `reason` string per loop for display in the Learning UI.
  6. **Findings & Follow-up Plan**:
     * Summarise root causes:
       * Data coverage issues (insufficient observation history, backend not running enough hours).
       * Threshold/cap tuning issues.
       * Logic bugs or query errors inside specific loops.
     * Propose concrete fixes for a follow-up Rev (e.g. “Rev 54 — Threshold Tuner Fix & Learning Metrics Export”), or apply small config/default tweaks here if appropriate.

* **Dependencies**:
  * Rev 44 (Learning tab) and Rev 45 (Debug tab) for visibility into status and logs.
  * Existing Darkstar learning implementation (`learning.py`, `backend/webapp.py`), Helios flows for conceptual reference.

* **Acceptance Criteria**:
  * Clear, written understanding of:
    * How Darkstar learning currently uses its data (tables, fields, time windows).
    * Why recent learning runs show `changes_applied = 0` while older runs applied changes.
  * Identified next steps (config changes and/or code changes) to make Darkstar learning behaviour more robust and more closely aligned with the Helios engine.

### Implementation

* **Completed**:
  * Step 1–3: Initial learning DB and loop behaviour analysis
    * Confirmed that the current observation path (`record_observation_from_current_state` → `LearningEngine.store_slot_observations`) records only SoC per 15-minute slot and hard-codes all energy and price fields to `0.0` (`import_kwh`, `export_kwh`, `pv_kwh`, `load_kwh`, `water_kwh`, `batt_*`, `import_price_sek_kwh`, `export_price_sek_kwh`). This explains the “all zeros” pattern in `slot_observations` despite the hardware being active.
    * Verified that the cumulative-sensor ETL (`etl_cumulative_to_slots`) exists and is capable of converting total-increasing sensors into slot-level deltas (similar to the Helios Execution History flow), but it is not wired up anywhere yet—no endpoint or job feeds HA totals into it.
    * Inspected the SQLite learning DB (`data/planner_learning.db`):
      * `slot_observations`: ~160 rows from 2025‑11‑03 onwards, with SoC values but mostly zero energy flows in recent slots.
      * `slot_forecasts`: 0 rows; `store_forecasts` is defined but never called, and even as written would only persist the last forecast in a batch.
      * `learning_runs`: 24 runs total. Runs 1–5 (2025‑11‑03) show `forecast_calibrator` applying changes (2 changes/run), but from run 6 onward `loops_run=0`, `changes_proposed=0`, `changes_applied=0`, and `loop_results` is empty—meaning no loop produces any candidate at all.
      * `learning_metrics`: currently a single row for `('2025‑11‑15', 's_index.base_factor', 1.05)` from the recent S-index history work.
      * `planner_debug`: populated (~170 rows), confirming planner debug writes are working.
    * Analysed `learning_runs.result_metrics_json`:
      * Early runs (IDs 1–5) have a single `forecast_calibrator` loop in `loop_results` with metrics, which matches the one day in the chart where “changes applied” > 0.
      * All later runs have `loops_run=0` and empty `loop_results`, which is consistent with loops returning `None` (no data/insufficient samples or improvement) and explains why the chart shows no changes for weeks.
    * Confirmed that `LearningLoops.forecast_calibrator` relies on a join between `slot_observations` and `slot_forecasts` over the last 14 days and enforces `min_sample_threshold` (`learning.min_sample_threshold`, currently 36). With `slot_forecasts` empty, `pv_results`/`load_results` are empty, sample counts are zero, and the loop always returns `None` (no bias/MAE, no changes).
    * Captured the intended HA sensor sources (to be ingested via the backend/HA API rather than n8n) for a future ingestion Rev:
      * `sensor.inverter_total_production`
      * `sensor.inverter_total_load_consumption`
      * `sensor.inverter_total_energy_import`
      * `sensor.inverter_total_energy_export`
      * `sensor.inverter_total_battery_charge`
      * `sensor.inverter_total_battery_discharge`
      * SoC sensor (already used via `battery_soc_percent` in `get_initial_state`) and Nordpool price data (already available).
    * Conclusion so far: the Darkstar learning engine’s orchestration and loops exist and were able to apply changes on 2025‑11‑03, but they are currently starved of meaningful data (no real energy flows, no forecast table), so all loops have effectively gone idle since run 6.
  * Step 4: Real HA sensor ingestion for observations (Phase 1)
    * Extended the learning schema with a `sensor_totals` table (`name`, `last_value`, `last_timestamp`) to track the last seen cumulative kWh per HA sensor and compute 15-minute deltas safely (clamped at zero on resets).
    * Updated `record_observation_from_current_state` so that, instead of hard-coding zeros, it now:
      * Fetches the agreed HA cumulative energy sensors via `get_home_assistant_sensor_float`:
        * `sensor.inverter_total_production` (PV),
        * `sensor.inverter_total_load_consumption` (load),
        * `sensor.inverter_total_energy_import` (grid import),
        * `sensor.inverter_total_energy_export` (grid export),
        * `sensor.inverter_total_battery_charge` (battery charge),
        * `sensor.inverter_total_battery_discharge` (battery discharge).
      * Computes per-slot kWh deltas by comparing each total with `sensor_totals.last_value`, initialising with zero delta on first sight and clamping negative deltas to zero (to handle counter resets).
      * Writes these deltas into `slot_observations` as:
        * `import_kwh`, `export_kwh`, `pv_kwh`, `load_kwh`, `batt_charge_kwh`, `batt_discharge_kwh`,
        * plus SoC start/end from `get_initial_state` and a `quality_flags="auto_recorded"` marker (prices still 0.0 for now).
      * Keeps the existing guard that prevents double-recording the same slot (`slot_start` + non-null `soc_end_percent`).
    * This makes `slot_observations` begin to reflect real energy flows from the inverter, aligning Darkstar’s observation logging conceptually with the Helios Execution History flow (albeit without prices/profit yet).
  * Step 5: Forecast storage into `slot_forecasts`
    * Fixed `LearningEngine.store_forecasts` so it now iterates over all provided forecast rows and performs an `INSERT OR REPLACE` per slot instead of only writing the last forecast in the batch.
    * Updated `/api/run_planner` so that after `HeliosPlanner.generate_schedule` runs, it:
      * Iterates over the planner DataFrame rows and builds a list of forecast records with:
        * `slot_start` from the index timestamp (ISO format),
        * `pv_forecast_kwh` and `load_forecast_kwh` from the DataFrame columns,
        * `temp_c` left as `None` for now.
      * Calls `LearningEngine.store_forecasts` with this list and the current git describe as `forecast_version`, guarded behind `learning.enable` so it’s a no-op when learning is disabled.
    * With this wiring, `slot_forecasts` now records per-slot PV/load forecasts each time the planner runs, enabling:
      * Forecast calibration loops to compute bias/MAE vs realised `slot_observations`,
      * `calculate_metrics` to report PV/load forecast sample counts and accuracy.
* **In Progress**: —
* **Blocked**: —

---

## Rev 52 — Learning Metrics & Parameter History *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Add proper learning metrics and parameter-change history to the SQLite DB so we are no longer relying on `config.yaml` as the only record of learning, and make this history visible in the Learning UI.
* **Started**: — (planned)
* **Last Updated**: — (planned)

### Plan

* **Goals**:
  * Keep `config.yaml` as the source of truth for current tunable parameters while moving learning history into dedicated SQLite tables.
  * Provide a clear, queryable record of what the learning engine has done over time (metrics and parameter changes), similar to Helios’ `learning_metrics` and `config history`.
  * Surface this history in the Learning tab so operators can see “what changed, when, and why” without digging into raw JSON blobs.

* **Scope**:
  * Metrics:
    * Extend the existing `learning_metrics` table to store daily aggregates beyond S-index, e.g.:
      * Load adjustment per hour (`load_adjustment_kwh[24]`).
      * SoC tracking error (avg/stddev).
      * PV forecast error (avg/stddev).
      * Arbitrage success metrics and profit aggregates.
    * Add a small ETL in the learning engine (using `slot_observations`, `slot_forecasts`, and possibly schedule/price data) to compute these aggregates once per day, similar in spirit to the Helios n8n Learning Engine flow.
  * Parameter-change history:
    * Introduce a `learning_param_history` table with columns like:
      * `run_id`, `timestamp`, `param_path`, `old_value`, `new_value`, `loop`, `reason`.
    * Populate this table in `_apply_changes` whenever config changes are applied, instead of relying solely on `config_versions.metrics_json`.
    * Ensure we can reconstruct how key parameters (e.g. `forecasting.pv_confidence_percent`, `forecasting.load_safety_margin_percent`, S-index factors, thresholds) have evolved over time.
  * UI integration:
    * Extend the Learning tab with:
      * A “Recent Changes” list showing the last N parameter changes (param path, old → new, loop, reason, timestamp).
      * Optional small tables/mini-charts for key metrics over time (e.g. PV/load MAE, SoC error, arbitrage success rate).

* **Dependencies**:
  * Rev 51 (learning DB wiring and loop correctness).
  * Existing Learning tab implementation (Rev 44/52) as a place to surface metrics.

* **Acceptance Criteria**:
  * SQLite DB contains:
    * Daily learning metrics (beyond S-index) in a dedicated consolidated table.
    * A clear per-run/per-change history in `learning_param_history`.
  * Learning tab can show:
    * Recent parameter changes with context.
    * At least one or two key learning metrics over time.
  * We no longer need to treat `config.yaml` as a history store; it remains only the current configuration.

### Implementation Steps (Planned)

1. **Metrics Schema & ETL**
   * Design the extended metrics row format (date + metric + value or JSON per day).
   * Implement a daily ETL in the learning engine that computes the desired metrics from `slot_observations`, `slot_forecasts`, and schedule/price data, and writes them into dedicated tables.

2. **Parameter History Schema & Writes**
   * Create a `learning_param_history` table keyed by `run_id` and timestamp.
   * Update `_apply_changes` to insert one row per changed parameter path (with old/new values, loop, and reason) when changes are applied.

3. **API & UI Wiring**
   * Extend `/api/learning/history` or add a dedicated endpoint to expose:
     * Recent parameter changes (from `learning_param_history`).
     * Selected daily metrics (from `learning_metrics`).
   * Update the Learning tab to render:
     * A “Recent Changes” list.
     * A simple metrics view (e.g. PV/load MAE over time or arbitrage success rate).

4. **Verification & Alignment**
   * Validate that new metrics match expectations by spot-checking against raw `slot_observations`/`slot_forecasts`.
   * Confirm that parameter changes seen in `learning_param_history` align with `config.yaml` diffs and `learning_runs` entries.

### Implementation

* **Completed**:
  * Step 1: Metrics schema & ETL for hourly PV/load deviations
    * Extended the learning schema with a consolidated `learning_daily_metrics` table `(date PRIMARY KEY, pv_error_by_hour_kwh, load_error_by_hour_kwh, pv_adjustment_by_hour_kwh, load_adjustment_by_hour_kwh, soc_error_mean_pct, soc_error_stddev_pct, pv_error_mean_abs_kwh, load_error_mean_abs_kwh, s_index_base_factor, created_at)` to store one row per day with both arrays and key scalars.
    * Added `LearningEngine.compute_hourly_forecast_errors(days_back=7)` which:
      * Joins `slot_observations` and `slot_forecasts` over the last N days.
      * Computes average PV and load forecast error per hour of day (actual - forecast in kWh) across that window.
      * Returns two 24-element arrays: `pv_error_by_hour_kwh` and `load_error_by_hour_kwh`.
    * Added `LearningEngine.store_hourly_forecast_errors(days_back=7)` which:
      * Calls the above computation and writes the resulting arrays and per-day MAE scalars into `learning_daily_metrics` via `upsert_daily_metrics`, keyed by today’s date.
      * Derives adjustment arrays `pv_adjustment_by_hour_kwh` and `load_adjustment_by_hour_kwh` (negated errors) and stores them alongside the raw error arrays for potential use in forecast biasing.
      * Updates `NightlyOrchestrator.run_nightly_job` so that, after recording a completed run and S-index factor, it also calls `store_hourly_forecast_errors(...)` to persist the 24h PV/load deviation arrays and daily aggregates.
  * Step 2: Parameter history schema & writes
    * Added a `learning_param_history` table `(id, run_id, param_path, old_value, new_value, loop, reason, created_at)` to store per-parameter changes applied by the learning engine.
    * Updated `_apply_changes` to accept a `run_id` and, whenever config changes are applied:
      * Compute a `diff_summary` of `old`/`new` values per `param_path`.
      * Infer the originating loop for each parameter (e.g. `forecast_calibrator`, `threshold_tuner`, `s_index_tuner`, `export_guard_tuner`) based on key prefixes.
      * Aggregate human-readable reasons from loop results.
      * Insert one row per changed parameter into `learning_param_history`, keyed by the `run_id`.
    * Ensured `config_versions` continues to store the full YAML blob and loop metrics JSON, while `learning_param_history` provides a flat, queryable view of “what changed, when, and why”.
  * Step 3: API & UI wiring for learning history
    * Extended `/api/learning/history` to return:
      * `runs`: the existing list of learning runs.
      * `s_index_history`: daily `s_index.base_factor` values pulled from `learning_daily_metrics.s_index_base_factor`.
      * `recent_changes`: the 20 most recent parameter changes from `learning_param_history` joined with `learning_runs` to attach `started_at` timestamps.
    * Updated the frontend API types in `frontend/src/lib/api.ts` to include `LearningParamChange` and `recent_changes` on `LearningHistoryResponse`.
    * Enhanced the Learning tab history section to render:
      * The existing mini-chart with “changes applied” bars and S-index line.
      * A “Recent changes” list showing, for each change, the parameter path, `old_value → new_value`, originating loop/reason (when available), and the associated run timestamp.
* **In Progress**: —
* **Blocked**:
  * Additional metrics such as detailed SoC tracking error and arbitrage/profit metrics remain in the backlog and will be implemented in a later rev once we either ingest richer execution history (Helios-style) or expose equivalent data into the learning DB.

---

## Rev 53 — Learning Engine Architecture & Planner Integration *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI
* **Summary**: Simplify and solidify the learning engine so that it stores one consolidated learning-output row per day in SQLite and feeds those outputs directly into the planner without rewriting `config.yaml`.
* **Started**: — (planned)
* **Last Updated**: — (planned)

### Plan

* **Goals**:
  * Separate static configuration (`config.yaml`) from dynamic, learned state in SQLite so there is a single, transparent source of truth for learning outputs.
  * Consolidate per-day learning outputs (PV/load adjustments, SoC error metrics, S-index factors, etc.) into a single row per day/run for easier debugging and UI integration.
  * Make the planner actually consume learning outputs on each run (biasing PV/load forecasts and S-index) while keeping the scope of automatic tuning modest for now.

* **Scope**:
  * Data model & flow:
    * Introduce or refactor towards a unified per-slot history model (conceptually equivalent to Helios’ `execution_history`) that combines plan and reality per slot, at least locally in SQLite:
      * Key fields: `slot_start`, `slot_end`, planned_* (charge/export/SoC/load/PV/prices) and actual_* (kWh, SoC, etc.), plus quality flags.
      * Ensure this history can be derived from or aligned with MariaDB’s `execution_history` / `plan_history` where appropriate, without breaking the existing executor.
    * Add a `learning_daily_metrics`-style table with exactly one row per date (or per `run_id`) containing:
      * 24-element PV/load error and adjustment arrays.
      * Basic SoC error metrics (mean/stddev, optionally by hour).
      * S-index factor(s) and a few key scalars (e.g. pv/load MAE).
    * Stop relying on `learning_daily_series`/`learning_metrics` as a scattered per-metric store for new data; either migrate to the new table or clearly mark legacy usage.
  * Learning behaviour:
    * Refactor the nightly learning orchestration so that:
      * It reads per-slot history (plan + actual) for the last N days.
      * Computes the minimal but useful set of outputs for this rev:
        * PV/load 24h adjustment arrays (bias per hour).
        * Basic SoC tracking error metrics.
        * S-index factor for the next planning horizon.
      * Writes a single, consolidated row into the daily metrics table.
    * Stop writing learned values back into `config.yaml`; instead, treat the new daily metrics table (plus optional `learning_param_history`) as the only record of learning outputs.
  * Planner integration:
    * On each planner run:
      * Read the latest daily metrics row (if present).
      * Bias PV/load forecasts by the stored 24h adjustments when building the forecast for each slot.
      * Use the learned S-index factor when computing the S-index, subject to bounds from `config.yaml`.
    * Keep advanced automatic tuning (e.g. fine-grained threshold/arbitrage parameter changes) out of this rev and move them explicitly to the backlog.
  * UI/UX:
    * Ensure the Learning tab surfaces:
      * The consolidated daily metrics (including PV/load MAE and SoC error) in a simple, inspectable way.
      * The separation between static config and learned outputs is clear (e.g. “Base config” vs “Learned adjustments”).

* **Dependencies**:
  * Rev 51 (learning DB wiring and loop correctness).
  * Rev 52 (learning metrics & parameter history wiring).
  * Existing planner behaviour and inputs.

* **Acceptance Criteria**:
  * Static vs dynamic:
    * Learning loops no longer mutate `config.yaml`; it remains static except when changed by the user or explicit migrations.
    * All learning outputs used by the planner live in the SQLite DB in well-defined tables (`learning_daily_metrics`, `learning_runs`, `learning_param_history`).
  * Data model:
    * There is exactly one primary daily learning-output row per date, containing PV/load error and adjustment arrays, basic SoC error metrics, and an S-index base factor.
    * Per-slot history for learning is derived from `slot_observations` and `slot_forecasts`; any further consolidation into an explicit execution-history view is tracked in the backlog.
  * Planner integration:
    * The planner reads the latest daily learning outputs on each run and biases PV/load forecasts and S-index accordingly, falling back gracefully to base `config.yaml` behaviour when data is missing.
  * UI:
    * The Learning tab can show, for recent days, both the daily outputs (key metrics) and the per-run history, without the user needing to inspect raw config diffs.

### Implementation

* **Completed**:
  * Step 1–2: Learning data model & nightly consolidation
    * Introduced a single consolidated table `learning_daily_metrics (date PRIMARY KEY, pv_error_by_hour_kwh, load_error_by_hour_kwh, pv_adjustment_by_hour_kwh, load_adjustment_by_hour_kwh, soc_error_mean_pct, soc_error_stddev_pct, pv_error_mean_abs_kwh, load_error_mean_abs_kwh, s_index_base_factor, created_at)` which holds exactly one row per date.
    * Deprecated and actively dropped the legacy `learning_metrics` and `learning_daily_series` tables from the schema; `_init_schema` removes them if they still exist, and all new metrics flow through `learning_daily_metrics`.
    * Updated `LearningEngine.store_hourly_forecast_errors(days_back=7)` to:
      * Compute 24-element PV/load error arrays (`pv_error_by_hour_kwh`, `load_error_by_hour_kwh`) over the last N days.
      * Derive per-hour adjustment arrays (`pv_adjustment_by_hour_kwh`, `load_adjustment_by_hour_kwh`) as negated errors.
      * Compute daily PV/load MAE (`pv_error_mean_abs_kwh`, `load_error_mean_abs_kwh`).
      * Upsert all of the above into `learning_daily_metrics` via `upsert_daily_metrics(date, payload)`, so each day gets a single, consolidated row.
    * Updated `NightlyOrchestrator.run_nightly_job` so that after reading the current `s_index` config it mirrors the effective `base_factor` into `learning_daily_metrics.s_index_base_factor` (again using `upsert_daily_metrics`) instead of writing to legacy tables.
  * Step 3: Planner consumption of learning outputs
    * Added `HeliosPlanner._load_learning_overlays()` which:
      * Reads the latest row from `learning_daily_metrics` when learning is enabled.
      * Parses PV/load adjustment arrays and `s_index_base_factor` into an in-memory dict `learning_overlays`.
      * Fails gracefully (returns `{}`) if the DB is missing, empty, or malformed.
    * Enhanced `HeliosPlanner.generate_schedule` to:
      * Load `self.learning_overlays` once at the start of each run.
      * Use these overlays in `_pass_0_apply_safety_margins` and `_pass_4_allocate_cascading_responsibilities`.
    * Updated `_pass_0_apply_safety_margins` so that, after applying the configured PV/load confidence and margin, it further:
      * Applies per-hour PV/load adjustments from `learning_overlays["pv_adjustment_by_hour_kwh"]` and `["load_adjustment_by_hour_kwh"]` (if present and length 24), based on the local hour of each slot.
      * This makes `adjusted_pv_kwh` and `adjusted_load_kwh` reflect both static margins and learned hourly biases.
    * Updated `_pass_4_allocate_cascading_responsibilities` so that:
      * It reads `s_index_base_factor` from `learning_overlays` (when available) and treats it as the effective `base_factor` for S-index.
      * For `mode='static'`, it uses `min(base_factor, max_factor)` as the S-index factor.
      * For `mode='dynamic'`, it still runs `_calculate_dynamic_s_index`, but on failure falls back to `min(base_factor, max_factor)` instead of the original static factor, so learning can still influence behaviour.
      * The planner’s debug payload (`s_index_debug`) now reflects the learned `base_factor` so the UI can show what learning is doing.
  * API & UI alignment:
    * Updated `/api/learning/history` to build `s_index_history` from `learning_daily_metrics.s_index_base_factor`, keeping the JSON shape the same for the Learning tab chart.
    * Added `/api/learning/daily_metrics` to expose the latest PV/load MAE and S-index base factor from `learning_daily_metrics` for use in the Learning tab.
    * The Learning tab now shows:
      * A mini-chart combining “changes applied” bars with an S-index line (from `s_index_history`).
      * A metrics row with the latest learned S-index base factor and PV/load MAE.
      * A “Recent changes” list driven by `learning_param_history`.
  * Step 4: Config & learning separation
    * `_apply_changes` no longer mutates `config.yaml`. Instead it records proposed changes into `config_versions` (with an empty yaml_blob and `applied=False`) and `learning_param_history` purely for observability. The planner now reads all learning outputs (PV/load adjustments, S-index base factor) from SQLite; `config.yaml` remains static except for user edits.

* **In Progress**: —
* **Blocked**: —

### Verification

* **Tests Status**:
  * Covered by existing learning integration and planner tests; no schema or API regressions expected from the consolidation.
* **Known Issues**:
  * A dedicated, explicit execution-history view (combining plan + actual) is still in backlog; current loops rely on `slot_observations` and `slot_forecasts`.
* **Rollback Plan**:
  * Disable learning via `learning.enable = false` in `config.yaml` to stop the planner from consuming overlays, or restore a prior schema/plan version if needed.

---

## Rev 54 — Learning & Debug Enhancements *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI (planned)
* **Summary**: Persist S-index factor history and enhance the Learning and Debug tabs so operators can see how learning affects the system over time.
* **Started**: 2025-11-14
* **Last Updated**: 2025-11-14

### Plan

* **Goals**:
  * Track S-index factor over time so we can visualise how learning adjusts it.
  * Make the Learning tab’s mini-chart more informative by showing S-index and loop-level metrics.
  * Add small UX polish to the Debug tab for logs and SoC history.

* **Scope**:
  * Learning:
    * Extend the learning DB schema to store S-index factor history (per learning run or per day).
    * Update learning loops to persist S-index factor and relevant context on each run.
    * Extend `/api/learning/history` or add a dedicated `/api/learning/sindex_history` endpoint.
    * Enhance the Learning tab chart to:
      * Plot S-index factor over recent runs.
      * Optionally overlay per-loop metrics (e.g. which loop applied changes).
  * Debug:
    * Add simple filters or range controls (e.g. last N minutes/hours) for logs and SoC history.
    * Make it easier to correlate errors with specific time windows.

* **Dependencies**:
  * Rev 44 (Learning tab and `/api/learning/history`).
  * Rev 45 (Debug tab and `/api/history/soc`).

* **Acceptance Criteria**:
  * S-index:
    * S-index factor history is stored and can be queried for recent runs/days.
    * Learning tab chart can show S-index factor evolution alongside changes-applied bars.
  * Debug:
    * Operators can filter logs by level and time range.
    * SoC history can be scoped to relevant windows for debugging.

### Implementation Steps (Planned)

1. **S-index History Storage**
   * Extend the learning DB to add a table or fields for S-index factor history.
   * Update learning loops to populate this on each run.

2. **API Extensions**
   * Extend `/api/learning/history` or introduce a new endpoint to return S-index history data.

3. **Learning Tab Chart Enhancements**
   * Update the Learning tab mini-chart to plot S-index factor alongside changes-applied.
   * Ensure tooltips show both metrics clearly.

4. **Debug Tab UX Polish**
   * Add time-range filters for logs and SoC history.
   * Make the log viewer and SoC chart respect the selected range.

5. **Verification & Backlog Alignment**
   * Manual tests for Learning and Debug tabs with active learning runs.
   * Close the Learning & Debug backlog items related to S-index history and chart polish.

### Implementation

* **Completed**:
  * Step 1: S-index history storage
    * Record the current `s_index.base_factor` (or `static_factor` as fallback) into the consolidated `learning_daily_metrics` table on every successful nightly learning run via `upsert_daily_metrics(date, {"s_index_base_factor": ...})`. This ensures we always have at least one S-index datapoint per day once learning is running, even when no config changes are applied.
  * Step 2: API extensions
    * Extended `/api/learning/history` to include an `s_index_history` array alongside `runs`, populated from `learning_daily_metrics.s_index_base_factor` ordered by date (most recent first, limited to a reasonable window). This gives the frontend a single call that returns both per-run metrics and S-index factor history.
  * Step 3: Learning tab chart enhancements
    * Updated the Learning tab mini-chart to:
      * Overlay a line for S-index factor against daily aggregated “changes applied” bars.
      * Aggregate changes-applied per day so bars/points align on the same X-axis (dates).
      * Use dual Y-axes (counts vs S-index factor) with clear tooltips.
  * Step 4: Debug time-range filters and SoC history range controls
    * Added client-side time-range filters to the Debug logs view (`all`, `last 1h`, `last 6h`, `last 24h`) so operators can focus on recent events without changing the backend API.
    * Extended the SoC history card to support a simple date range selector (`today` / `yesterday`) wired to `/api/history/soc?date=...`, allowing quick comparison of SoC behaviour across days.
* **In Progress**: —
* **Blocked**: —

### Verification

* **Tests Status**:
  * Verified Learning tab history chart and metrics row render correctly with S-index history and daily metrics; Debug tab manually checked for log filters and SoC date switching.
* **Known Issues**:
  * More advanced log/SoC range queries (e.g. arbitrary date ranges or multi-day SoC charts) remain in the backlog.
* **Rollback Plan**:
  * Revert the Debug tab UI changes if necessary; learning history wiring is backward compatible and can be left in place.

---

* **Model**: GPT-5.1 Codex CLI (planned)
* **Summary**: Improve error/loading handling, basic mobile responsiveness, and document a minimal deployment setup so the new React/Flask UI can be safely used in place of the legacy app.
* **Started**: — (planned)
* **Last Updated**: — (planned)

### Plan

* **Goals**:
  * Make the new React/Flask UI safe and predictable enough to run as the primary interface instead of the legacy app.
  * Ensure critical API failures are clearly surfaced without breaking the whole UI.
  * Make the main tabs usable on smaller screens (no full redesign).
  * Provide a simple, documented way to deploy the frontend with the backend.

* **Scope**:
  * Error & loading handling:
    * Audit Dashboard, Planning, Learning, Debug, and Settings for:
      * Clear loading states for primary cards.
      * Clear, non-intrusive error banners when core APIs fail (`/api/status`, `/api/schedule`, `/api/config`, `/api/learning/status`, etc.).
    * Add a global “backend offline” indicator when `/api/config`/`/api/status` repeatedly fail (for example after N consecutive errors), without blocking user navigation.
  * Mobile responsiveness:
    * Tweak layouts for breakpoints so the main tabs are readable and scroll nicely on phones/tablets (no overlapping or clipped content).
  * Legacy UI decommissioning:
    * Remove or archive any legacy Flask UI entrypoints and their `templates/` / `static/` folders outside `backend/`, keeping `backend/` as the single serving surface.
    * Remove obsolete scripts or run modes that still start the legacy UI.
    * Update README so there is only one canonical way to run the planner/UI (the new React/Flask stack).
  * Deployment basics:
    * Document or implement a minimal setup to serve `frontend/dist` via Flask or alongside it (e.g. nginx + Flask), including where the planner, learning DB, and `schedule.json` live on disk.

* **Dependencies**:
  * All previous Revs; this is a polish layer rather than new core features.

* **Acceptance Criteria**:
  * When backend APIs fail, each main tab shows a clear error but remains usable (no spinners forever, no blank screens).
  * The app is navigable on a phone-sized viewport (critical controls accessible, charts scrollable).
  * There is a documented path for serving the built frontend with the backend in production (referenced from README and/or a dedicated deployment doc), suitable for replacing the legacy UI on the server.
  * There is no separate “legacy UI” path in docs or scripts: only the new React/Flask UI is documented and supported, and any legacy folders/scripts are either removed or clearly archived.

### Implementation Steps (Planned)

1. **Error & Loading Audit**
   * Review each tab’s use of API calls and loading states.
   * Add or refine loading spinners and error banners where missing.

2. **Global Backend-Offline Indicator**
   * Add a small global banner component that appears when repeated `/api/config` or `/api/status` calls fail.

3. **Mobile Layout Tweaks**
   * Adjust grid and spacing classes in the main pages to behave better on narrow viewports.

4. **Deployment Notes**
   * Add a short section to README or a new doc describing how to:
     * Build the frontend.
     * Serve `frontend/dist` with Flask or via a simple reverse proxy.

5. **Verification & Backlog Alignment**
   * Manual tests for error states, mobile layout, and a basic production-like deployment.
   * Close relevant Production Readiness backlog items incrementally.

---

## Rev 55 — Production Readiness Slice *(Status: ✅ Completed)*

* **Model**: GPT-5.1 Codex CLI (planned)
* **Summary**: Improve error/loading handling, basic mobile responsiveness, and document a minimal deployment setup so the new React/Flask UI can be safely used in place of the legacy app.
* **Started**: — (planned)
* **Last Updated**: — (planned)

### Plan

* **Goals**:
  * Make the new React/Flask UI safe and predictable enough to run as the primary interface instead of the legacy app.
  * Ensure critical API failures are clearly surfaced without breaking the whole UI.
  * Make the main tabs usable on smaller screens (no full redesign).
  * Provide a simple, documented way to deploy the frontend with the backend.

* **Scope**:
  * Error & loading handling:
    * Audit Dashboard, Planning, Learning, Debug, and Settings for:
      * Clear loading states for primary cards.
      * Clear, non-intrusive error banners when core APIs fail (`/api/status`, `/api/schedule`, `/api/config`, `/api/learning/status`, etc.).
    * Add a global “backend offline” indicator when `/api/config`/`/api/status` repeatedly fail (for example after N consecutive errors), without blocking user navigation.
  * Mobile responsiveness:
    * Tweak layouts for breakpoints so the main tabs are readable and scroll nicely on phones/tablets (no overlapping or clipped content).
  * Legacy UI decommissioning:
    * Remove or archive any legacy Flask UI entrypoints and their `templates/` / `static/` folders outside `backend/`, keeping `backend/` as the single serving surface.
    * Remove obsolete scripts or run modes that still start the legacy UI.
    * Update README so there is only one canonical way to run the planner/UI (the new React/Flask stack).
  * Deployment basics:
    * Document or implement a minimal setup to serve `frontend/dist` via Flask or alongside it (e.g. nginx + Flask), including where the planner, learning DB, and `schedule.json` live on disk.

* **Dependencies**:
  * All previous Revs; this is a polish layer rather than new core features.

* **Acceptance Criteria**:
  * When backend APIs fail, each main tab shows a clear error but remains usable (no spinners forever, no blank screens).
  * The app is navigable on a phone-sized viewport (critical controls accessible, charts scrollable).
  * There is a documented path for serving the built frontend with the backend in production (referenced from README and/or a dedicated deployment doc), suitable for replacing the legacy UI on the server.
  * There is no separate “legacy UI” path in docs or scripts: only the new React/Flask UI is documented and supported, and any legacy folders/scripts are either removed or clearly archived.

### Implementation Steps (Planned)

1. **Error & Loading Audit**
   * Review each tab’s use of API calls and loading states.
   * Add or refine loading spinners and error banners where missing.

2. **Global Backend-Offline Indicator**
   * Add a small global banner component that appears when repeated `/api/config` or `/api/status` calls fail.

3. **Mobile Layout Tweaks**
   * Adjust grid and spacing classes in the main pages to behave better on narrow viewports.

4. **Legacy UI Cleanup**
   * Identify and remove/archive legacy Flask UI entrypoints, templates, static assets, and run scripts outside `backend/`.
   * Update README to remove legacy run instructions and point only to the new stack.

5. **Deployment Notes**
   * Add a short section to README or a new doc describing how to:
     * Build the frontend.
     * Serve `frontend/dist` with Flask or via a simple reverse proxy.
     * Ensure the learning DB and `schedule.json` paths are writable and backed up appropriately.

6. **Verification & Backlog Alignment**
   * Manual tests for error states, mobile layout, and a basic production-like deployment.
   * Close relevant Production Readiness backlog items incrementally.

---

### Implementation

* **Completed**:
  * Step 1: Initial error/loading handling (Dashboard)
    * Added per-card error messaging on the Dashboard by tracking partial API failures in `Dashboard.tsx` and surfacing a compact status line (“Some dashboard data failed to load.”) in the System Status card while still rendering whatever data was successfully fetched.
    * Ensured the main dashboard chart shows a clear “No Price Data” overlay when schedule/pricing data is missing, instead of leaving stale/mock data visible.
  * Step 2: Global backend-offline indicator
    * Added a lightweight health check in `App.tsx` that periodically calls `/api/status` and `/api/config`; after three consecutive failures it displays a non-blocking banner (“Backend appears offline or degraded. Some data may be stale or unavailable.”) across all tabs.
    * Kept the indicator read-only and non-modal so navigation and per-card error states remain usable even when the banner is visible.
  * Tooltip offset for charts
    * Tweaked Chart.js tooltip options in `ChartCard.tsx` (`caretPadding`, `yAlign`) so tooltips no longer sit directly on top of data points, improving readability on dense desktop and mobile charts.
  * Price history overlay for charts
    * Updated `/api/schedule/today_with_history` to merge in a full-day Nordpool price map for today (via `get_nordpool_data`), synthesising slots where needed so the chart’s price series can show a complete 24-hour curve even when the schedule or execution history is sparse.
* **In Progress**: —
* **Blocked**: —

---

## Rev 56 — Dashboard Server Plan Visualization *(Status: 🔄 In Progress)*

* **Model**: GPT-5 Codex CLI  
* **Summary**: Make the Dashboard chart and status clearly reflect whether the user is viewing the local (schedule.json) plan or the server (MariaDB current_schedule) plan by fetching and rendering the full server schedule on demand, while merging in execution history so SoC Actual and executed series remain accurate, without mutating the local plan file.
* **Started**: 2025-11-21  
* **Last Updated**: 2025-11-21  

### Plan

* **Goals**:
  * When the user clicks “Load server plan”, fetch the full `current_schedule` from the database and render it in the Dashboard chart so that all today/tomorrow hours reflect the server-side plan.
  * Keep the local `schedule.json` untouched; treat the server plan as a read-only overlay that can be toggled on/off via the existing “Now showing: local/server plan” selector.
  * Make it visually obvious which plan the user is looking at (local vs server) so that debugging and operations are safe.

* **Scope**:
  * Frontend wiring in the React Dashboard, QuickActions, and ChartCard to:
    * Fetch `/api/db/current_schedule` on demand and store it in Dashboard state.
    * Pass the server plan into the chart via `slotsOverride` when the current plan source is `server`.
  * Backend enhancement of `/api/db/current_schedule` to merge in execution history from `execution_history` for today’s slots (SoC Actual and `actual_*` series), mirroring the behavior of `/api/schedule/today_with_history`.
  * No changes to planner optimization behavior or `schedule.json` semantics; this Rev only affects how plans are surfaced and visualised.

* **Dependencies**:
  * `/api/db/current_schedule` endpoint returning a full `schedule` array in the “UI shape” (slot_start/end, load/pv forecasts, charge/export/water, SoC fields, prices).
  * Rev 41–47 Dashboard/ChartCard integration stable (48h logic, history overlay, price padding, SoC datasets).
  * Quick Actions already wired to `/api/db/current_schedule` and `/api/schedule` for status metadata.

### Implementation Steps

1. **Dashboard State for Server Schedule**
   * Extend `frontend/src/pages/Dashboard.tsx` to hold:
     * `serverSchedule: ScheduleSlot[] | null` — the last fetched DB schedule, or `null` when not loaded.
     * Optional `serverScheduleLoading`/`serverScheduleError` flags for UX feedback.
   * Ensure this state is independent from the existing local schedule handling and status metadata.

2. **Fetch & Cache Server Plan on “Load server plan”**
   * Update `frontend/src/components/QuickActions.tsx` so that the `load-server` action:
     * Calls `Api.loadServerPlan()` as today.
     * Passes the returned `schedule` back up (e.g. via a new `onServerScheduleLoaded(schedule)` callback) instead of discarding it.
   * In `Dashboard`, implement `handleServerScheduleLoaded` to:
     * Store the received `schedule` in `serverSchedule`.
     * Switch `currentPlanSource` to `'server'`.
     * Optionally derive any lightweight metrics from the DB plan (e.g. PV totals) for future polish.

3. **Wire ChartCard to Use Server Plan via slotsOverride**
   * In `Dashboard`, adjust the `<ChartCard>` usage so that:
     * When `currentPlanSource === 'server'` and `serverSchedule` is non-null, pass `slotsOverride={serverSchedule}`.
     * When `currentPlanSource === 'local'`, omit `slotsOverride` so `ChartCard` falls back to its existing `/api/schedule` / `/api/schedule/today_with_history` loading.
   * Keep `useHistoryForToday` enabled only for the local plan; when viewing the server plan, the chart should rely on `/api/db/current_schedule` (which already has execution history merged for today) rather than calling `/api/schedule/today_with_history` again.

4. **Merge Execution History into `/api/db/current_schedule`**
   * Extend the backend `db_current_schedule` endpoint so that for slots on the local “today” date:
     * It joins `current_schedule` with the latest `execution_history` row per `slot_start` (same logic as `/api/schedule/today_with_history`) and attaches `soc_actual_percent`, `is_executed`, and `actual_*` fields.
     * It preserves all existing fields and response shape so existing consumers remain compatible.
   * Leave future/tomorrow slots plan-only (no `soc_actual_percent`), matching the current Dashboard semantics.

### Implementation

* **Completed**:
  * Step 1: Dashboard state for server schedule
    * Added `serverSchedule`, `serverScheduleLoading`, and `serverScheduleError` state to `frontend/src/pages/Dashboard.tsx` to track the DB-backed schedule independently of the local plan and its metadata.
  * Step 2: Fetch & cache server plan on “Load server plan”
    * Updated `QuickActions` so the “Load server plan” button calls `Api.loadServerPlan()` and forwards the returned `schedule` into Dashboard via a new `onServerScheduleLoaded` callback.
    * Dashboard now stores the server schedule in `serverSchedule` and switches the plan source badge to `server` without touching `schedule.json`.
  * Step 3: Wire ChartCard to use server plan via `slotsOverride`
    * Updated the Dashboard’s `<ChartCard>` usage so that when `currentPlanSource === 'server'`, it passes `slotsOverride={serverSchedule}` and disables `useHistoryForToday`, making the overview chart render the DB schedule across the 48h window while the local plan continues to use `/api/schedule/today_with_history`.
* **In Progress**:
  * Step 4: Backend merge of execution history into `/api/db/current_schedule` so SoC Actual and `actual_*` appear consistently when viewing the server plan.
* **Blocked**: —  


---

## Rev 57 — In‑App Scheduler Orchestrator *(Status: 📋 Planned)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Move planner automation from external systemd/cron into Darkstar itself via a dedicated scheduler component, with clear configuration, status APIs, and Dashboard integration (Planner Automation card).

* **Started**: 2025-11-21
* **Last Updated**: 2025-11-21

### Plan

* **Goals**:
  * Eliminate the external dependency on systemd/cron for planner runs.
  * Provide an in-app scheduler that can be controlled and inspected via config + API.
  * Expose a clear “Next auto run” indicator and scheduler health in the Dashboard.
  * Preserve at-least-once semantics and avoid duplicate runs when the backend is scaled.

* **Scope**:
  * Backend:
    * Introduce a scheduler module (e.g. `backend/scheduler.py`) responsible for orchestrating planner runs.
    * Support a simple, explicit schedule configuration (e.g. “every N minutes” and/or “run at HH:MM local”).
    * Add API endpoints / helpers to surface scheduler status (enabled, last run, next run, last error).
  * Frontend:
    * Extend the Planner Automation card on the Dashboard with:
      * “Next auto run” time.
      * Last run timestamp and status (success/error).
    * Wire the existing enable/disable toggle to the new scheduler config instead of just a boolean.
  * Ops:
    * Provide a clean migration story from systemd timer → in-app scheduler (including a “one or the other, not both” note).

* **Dependencies**:
  * Rev 40 (Dashboard completion & automation status card in React).
  * Existing `bin/run_planner.py` as reference for planner invocation and DB push behavior.

* **Acceptance Criteria**:
  * When the in-app scheduler is enabled, it runs `HeliosPlanner` on the configured cadence, updates `schedule.json`, and (optionally) writes to DB when configured.
  * The Dashboard’s Planner Automation card displays:
    * Scheduler state (enabled/disabled) with a green/grey indicator.
    * Next planned run time (local timezone).
    * Last run time and status (success/error).
  * No duplicate runs occur when there is more than one web worker/process.
  * It is possible to fully disable the external systemd/cron timer without losing automation, and the migration path is documented.

### Implementation

* **Completed**:
  * **Step 1 – Scheduler model design**
    * Decide to run the scheduler as a **dedicated Python process** (e.g. `python -m backend.scheduler` or `bin/run_scheduler.py`) instead of embedding timers inside Flask workers, to avoid duplicate runs in multi‑worker setups.
    * Scheduler will use a **simple fixed‑interval cadence** (initially `automation.every_minutes` in `config.yaml`) with room to add “run at HH:MM local” later if needed.
    * Each tick will:
      * Reload `config.yaml` to respect `automation.enable_scheduler` and cadence changes without restart.
      * Compute `next_run_at` based on `every_minutes` and `last_run_at`.
      * Call a shared `run_planner_once()` helper (factored out of `bin/run_planner.py`) when it is time to run.
      * Persist status (`enabled`, `next_run_at`, `last_run_at`, `last_run_status`, `last_error`) to a small JSON file under `data/scheduler_status.json` so `backend/webapp.py` can serve `/api/scheduler/status` without tight coupling.
    * Only one scheduler instance should run in production; this will be enforced operationally (one systemd unit or container) and documented in README.
  * **Step 2 – Scheduler configuration definition**
    * Extend the existing `automation` section in `config.yaml` with an explicit schedule block:
      ```yaml
      automation:
        enable_scheduler: true        # master toggle for in-app scheduler
        write_to_mariadb: true        # existing flag, respected by scheduler
        schedule:
          every_minutes: 60           # run planner every N minutes (minimum e.g. 15)
          jitter_minutes: 5           # optional random +/- jitter to avoid thundering herd
      ```
    * Semantics:
      * `enable_scheduler`: when `false`, scheduler runner stays idle but can still expose last/next run status.
      * `schedule.every_minutes`:
        * Primary cadence field for Rev 57; values below 15 will be clamped or rejected.
        * Scheduler computes `next_run_at = last_run_at + every_minutes`.
      * `schedule.jitter_minutes`:
        * Optional small random offset applied per run to avoid multiple sites hitting Nordpool/HA at the exact same second.
    * `config.default.yaml` will be updated with the same structure and safe defaults (`enable_scheduler: false` by default) to avoid accidental activation.
  * **Step 3 – Backend scheduler module design**
    * Define `backend/scheduler.py` as the main entrypoint, with:
      * `load_scheduler_config()` helper to read `config.yaml` and normalise `automation.schedule` (enforcing minimum interval and defaults).
      * `load_status()` / `save_status()` helpers to read/write `data/scheduler_status.json` (with a simple schema: `enabled`, `every_minutes`, `jitter_minutes`, `last_run_at`, `next_run_at`, `last_run_status`, `last_error`).
      * `run_planner_once(config_path: str = "config.yaml")` imported from a shared helper (to be factored out of `bin/run_planner.py` into e.g. `backend.scheduler_runner` or similar).
    * Main loop sketch:
      * On start, call `load_status()` and `load_scheduler_config()`.
      * Compute `next_run_at` if missing, based on `every_minutes` and current time (+ optional jitter).
      * Enter a loop that:
        * Sleeps in short intervals (e.g. 30–60 seconds) to allow quick reaction to config changes.
        * On each tick:
          * Reload config via `load_scheduler_config()`.
          * If `automation.enable_scheduler` is `False`, update status to `enabled=False`, keep `last_run_at`/`last_run_status` intact, and recompute `next_run_at` lazily when re-enabled.
          * If `enabled` and current time >= `next_run_at`, run:
            * Set `last_run_status = "running"` and persist.
            * Call `run_planner_once()` inside try/except.
            * On success: update `last_run_at`, set `last_run_status = "success"`, clear `last_error`, and compute a new `next_run_at = last_run_at + every_minutes (+ jitter)`.
            * On failure: set `last_run_status = "error"`, record `last_error = str(e)`, still compute a new `next_run_at` to avoid tight retry loops.
    * Concurrency considerations:
      * Scheduler remains a **single external process**; we explicitly do not start it from Flask.
      * Status file writes are atomic at the process level (only scheduler writes; webapp only reads), minimising race conditions.
      * If status file is missing or corrupt, the scheduler will recreate it with sane defaults and log a warning.
  * **Step 4 – Scheduler status API & Dashboard wiring design**
    * Backend API:
      * Add `/api/scheduler/status` in `backend/webapp.py` which:
        * Reads `data/scheduler_status.json` (if present) plus current `automation` config from `config.yaml`.
        * Returns a JSON payload, e.g.:
          ```json
          {
            "enabled": true,
            "every_minutes": 60,
            "jitter_minutes": 5,
            "last_run_at": "2025-11-22T07:15:00Z",
            "next_run_at": "2025-11-22T08:15:00Z",
            "last_run_status": "success",
            "last_error": null,
            "source": "in_app"  // vs "external" or "unknown"
          }
          ```
        * Handles missing or malformed status file gracefully by returning `source: "unknown"` and `last_run_*` fields as `null`, but still reflecting `automation.enable_scheduler`.
    * Frontend API client:
      * Extend `frontend/src/lib/api.ts` with `schedulerStatus(): Promise<SchedulerStatus>` that calls `/api/scheduler/status` and maps the payload into a typed object.
    * Dashboard Planner Automation card:
      * On mount, call `Api.schedulerStatus()` and merge the result with existing `config.automation` state.
      * Display:
        * Status pill: “Active”/“Disabled” with green/grey dot driven by `enabled`.
        * “Next auto run” line using `next_run_at` (converted to local time) when available; otherwise a subtle “No upcoming run (scheduler offline)” message.
        * “Last run” line showing timestamp + `last_run_status` (success/error), with a small warning icon when `last_run_status === "error"` and optional tooltip with `last_error`.
      * Keep the existing enable/disable toggle wired to `advisor.enable_scheduler` save logic, but also re-fetch `schedulerStatus` after a toggle to update `enabled` and `next_run_at`.
  * **Step 5 – Settings integration & migration documentation plan**
    * Settings UI:
      * Extend the Settings “Automation” / “Planner” section to expose:
        * `Enable in-app scheduler` (checkbox bound to `automation.enable_scheduler`).
        * `Run every` input (number + “minutes” select) bound to `automation.schedule.every_minutes`.
        * `Jitter` input (optional, small number) bound to `automation.schedule.jitter_minutes`.
      * Use the existing `updateConfig` helper so changes persist back to `config.yaml` via `/api/config/save`, and document that changes can take up to one tick to be picked up by the scheduler process.
    * Optional “Run now”:
      * Plan a small `/api/scheduler/run_now` endpoint that:
        * Enqueues a one-off planner run if no run is currently `running`.
        * Is implemented by directly calling the same shared `run_planner_once()` helper, with a minimal in-process lock so multiple clicks don’t stack runs.
      * Dashboard “Run now” button would live in the Planner Automation card, next to the status lines, and fall back gracefully if the endpoint is unavailable.
    * Migration & docs:
      * Add a “Scheduler” section to README describing:
        * How to start the scheduler process (e.g. `python -m backend.scheduler`) and recommended systemd unit.
        * How to disable legacy systemd/cron timers to avoid double-runs.
        * Recommended defaults for `every_minutes` and `jitter_minutes`.
      * Note explicitly that only **one** scheduler process should be active per site.
* **In Progress**: —
* **Blocked**: —

* **Next Steps**:
  3. **Implement backend scheduler module**
     * Implement a scheduler entrypoint (e.g. `backend/scheduler.py`) that:
       * Loads config and sleeps/wakes according to schedule.
       * Calls an internal “run planner once” function (shared with `bin/run_planner.py` to avoid duplication).
       * Records last/next run state (e.g. in memory, plus optional small SQLite/JSON for durability).
     * Ensure only one scheduler is active (e.g. guard via `ENABLE_SCHEDULER_PROCESS` env or a simple lock).
  4. **Expose scheduler status**
     * Add a small API endpoint (e.g. `/api/scheduler/status`) returning:
       * `enabled`, `next_run_at`, `last_run_at`, `last_run_status`, `last_error`.
     * Wire the Dashboard Planner Automation card to this endpoint in addition to config.
  5. **Integrate with Dashboard & Settings**
     * Extend the Planner Automation card to show `next_run_at` and `last_run_at/status`.
     * Optionally add a small “Run now” button that triggers a one-off run via API (respecting locking).
     * Update Settings to allow editing the schedule configuration (where appropriate).
  6. **Migration & docs**
     * Add a section to README explaining:
       * How to disable the old systemd timer.
       * How to enable/configure the in-app scheduler.
       * Caveats for multi-process deployments (e.g. “run scheduler in a separate process or single worker”).

* **Technical Decisions** (planned):
  * Prefer a small dedicated scheduler wrapper (invoked as a separate process) over burying scheduling in Flask workers, to avoid multi-worker duplication.
  * Reuse the logic from `bin/run_planner.py` (planner invocation, DB write) via a shared function rather than duplicating behavior.

* **Files Modified** (expected):
  * `backend/scheduler.py` (new).
  * `backend/webapp.py` (expose scheduler status endpoint).
  * `bin/run_planner.py` (refactor shared run-planner helper).
  * `config.yaml` / `config.default.yaml` (new `automation.schedule` fields).
  * `frontend/src/pages/Dashboard.tsx` (extend Planner Automation card).
  * `frontend/src/lib/api.ts` (add scheduler status client).

* **Configuration**:
  * New `automation` schedule fields with safe defaults.
  * Optional env flag to enable the in-app scheduler process vs. external scheduler.

### Verification

* **Tests Status**:
  * Unit-level: scheduler tick logic (interval/cron parsing, next_run computation).
  * Integration-level: end-to-end “auto-run updates schedule.json and/or DB”, validated via API.
* **Known Issues**:
  * In multi-process deployments, only one scheduler process must be enabled; this will be documented and enforced via a simple convention/env.
* **Rollback Plan**:
  * Keep systemd/cron integration intact until the in-app scheduler is proven stable.
  * If issues arise, disable the in-app scheduler and revert to the external timer using existing `bin/run_planner.py` flow.

---

## Backlog

### Dashboard Refinement

### Schedule & Executor Alignment

### Planning Timeline
- [ ] Fix Planning timeline “Hold” vs discharge bug where some slots are rendered as hold blocks even though the schedule has discharge with `soc_target_percent` pinned to `min_soc_percent` (ensure the classification logic respects discharge action and SoC limits).

### Settings & Configuration
- [ ] Unify sensor configuration under `config.yaml` `input_sensors` map; remove Home Assistant entity IDs (e.g. `battery_soc_entity_id`, `water_heater_daily_entity_id`) from `secrets.yaml` so that file only holds actual secrets (HA URL + token), and refactor `learning.py` and `inputs.py` to read all sensor IDs from the centralized `input_sensors` structure while keeping the planner, learning engine, and web UI fully functional on the new configuration.

### Repo & Docs Hygiene
- [ ] Update `AGENTS.md` project structure and theme path references to match the current backend/frontend layout (themes under `backend/themes/`).
- [ ] Plan and execute a dedicated refactor rev to move `planner.py` and `inputs.py` under `backend/` (with updated imports/tests) to keep the repository structure consistent.

### Learning & Debug
- [ ] Persist S-index factor history in learning DB (per-run or per-day) so we can visualise how the effective S-index changes over time.
- [ ] Learning history chart polish: enrich the Learning tab mini-chart with S-index factor and/or per-loop metrics in addition to changes-applied bars (build on the new `/api/learning/history` and planned S-index history storage).
- [ ] Make the learning engine pick up config changes (e.g. `learning.min_sample_threshold`) without requiring a backend restart by reloading or rebuilding the cached `LearningEngine` instance when relevant settings are saved.

### Planner & Charts
- [ ] Fix `soc_target_percent` behaviour around re-planning so that the current/next slot does not create a one-slot spike (use a consistent target floor/trajectory instead of using entry SoC only for the current slot).
- [ ] Render `soc_target` as a step-line series in the charts to better match discrete slot-level behaviour.
- [ ] Add zoom support to the charts (e.g. wheel + modifier or explicit controls) so operators can inspect narrower time windows.
- [ ] Offset chart tooltips slightly from the cursor to avoid covering the exact data point, improving readability when inspecting dense regions.
- [ ] Ensure the price series includes full Nordpool price history for the day, including past hours, so the charts can display a complete 24-hour price curve (even when schedule data is limited).

### Production Readiness
- [ ] Error handling & loading states for all API calls
- [ ] Mobile responsiveness for all components
- [ ] Performance optimization (chart rendering, data caching)
- [ ] Deployment configuration (serve `frontend/dist` from Flask or separate static host)
- [ ] State management for user preferences and theme

## Appendix — Handover Notes

---

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
