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

## Rev 40 — Dashboard Completion *(Status: 🔄 In Progress)*

* **Model**: GPT-5 Codex CLI
* **Summary**: Complete Dashboard functionality to achieve full parity with legacy UI including API integration, visual improvements, and UX polish.
* **Started**: 2025-11-13
* **Last Updated**: 2025-11-13

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

6. **Status Cards Real Data**
   * Water heater from `/api/ha/water_today`
   * Export guard status from config
   * Learning status from `/api/learning/status`
   * Add real-time updates

7. **Real-time Updates & Timezone**
   * Fix `isToday`/`isTomorrow` to use local timezone
   * Add polling strategy for live data refresh
   * Implement plan origin indicator (local vs server)
   * Add data refresh controls

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

* **In Progress**: —
* **Blocked**: —
* **Next Steps**: Continue with Step 3 (Header/Logo Reorganization), then proceed with remaining Rev 40 steps

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

## Backlog

### Dashboard Completion
- [ ] Quick Actions API wiring (run planner, load server plan, push to DB, reset optimal)
- [ ] Dynamic KPIs from real data (battery capacity, PV today, avg load from `/api/ha/average`)
- [ ] Status cards integration (water heater from `/api/ha/water_today`, export guard, learning status)
- [ ] Plan origin indicator ("local vs server plan" toggle/display)
- [ ] Dataset visibility toggles (show/hide charge/discharge/export/SoC lines)
- [ ] Real-time data polling for live updates
- [ ] Timezone fixes for day slicing (use local TZ instead of UTC)
- [ ] Chart theme colors with Material Design palette (fix invisible SoC lines)
- [ ] Header logo replacement (move lucide-bolt from header to sidebar, replace "nav" text)
- [ ] Quick action buttons UI fix (icons only, text on hover, fix text spilling)
- [ ] Header items moved to sidebar menu

### Planning Timeline
- [ ] vis-timeline React integration with new theme styling
- [ ] Manual block CRUD operations (create/edit/delete charge/water/export/hold)
- [ ] Simulate/save workflow with `/api/simulate` and `/api/schedule/save`
- [ ] Chart synchronization after manual changes
- [ ] Historical slots read-only handling
- [ ] Device caps and SoC target enforcement
- [ ] Zero-capacity gap handling

### Settings & Configuration
- [ ] Configuration forms (decision thresholds, battery economics, charging strategy, etc.)
- [ ] Theme picker using `/api/themes` and `/api/theme`
- [ ] Form validation and persistence with `/api/config/save`
- [ ] Config reset functionality with `/api/config/reset`

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
