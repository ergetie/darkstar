# React Frontend Gap Analysis

Scope: compare the legacy Flask UI (templates/index.html + static assets) with the new React/Vite UI under `frontend/`, identify missing features, and map data contracts (endpoints and field shapes) required to reach functional parity. Focus priority: Dashboard first; Planning timeline and other tabs in Backlog.

---

## Navigation & Layout
- Legacy: Header + tabbed navigation (Dashboard, Settings, Learning, Debug, System). Single-page, vanilla JS.
- React: Sidebar + header and routes for `/`, `/planning`, `/learning`, `/debug`, `/settings`.
- Gap: React lacks the “System” tab; Settings/Learning/Debug are placeholders.

## Dashboard — Chart + Status
- Legacy: 48h chart with datasets:
  - Import price line (SEK/kWh)
  - PV forecast (kW, filled area)
  - Load forecast (kW, bars)
  - Battery charge/discharge (kW, bars)
  - Export (kWh, bars)
  - SoC target (%) and projected SoC (%) lines; possibly historical SoC
  - No “bridging” across missing data; 15-min resolution; local timezone rendering
  - Status widgets: SoC now; horizon lengths (PV/weather); “now showing: local plan/server plan” indicator
- React: `ChartCard` renders price/PV/load, and maps optional charge/discharge/export/socTarget/socProjected from `/api/schedule`. Day toggle (today/tomorrow) is present; Quick actions are stubs; status/horizon badges shown on Dashboard via `/api/status` and `/api/forecast/horizon` (partial implementation).
- Gaps:
  - Ensure all datasets are visible/toggled consistent with legacy semantics
  - Verify 48h window slice correctness and timezone (Europe/Stockholm)
  - Add “plan origin” indicator (local vs DB) and planner version timestamps
  - Add historical SoC vs projected/target if available

### Dashboard Endpoints & Contracts
- `/api/schedule` → `{ schedule: ScheduleSlot[] }`
  - React types (supported legacy aliasing):
    - `start_time: string; end_time?: string`
    - `import_price_sek_kwh?: number`
    - `pv_forecast_kwh?: number; load_forecast_kwh?: number`
    - `battery_charge_kw?: number; battery_discharge_kw?: number`
    - `charge_kw?: number; discharge_kw?: number` (legacy fallback)
    - `water_heating_kw?: number; export_kwh?: number`
    - `projected_soc_percent?: number; soc_target_percent?: number`
    - `is_historical?: boolean; slot_number?: number`
- `/api/status` → `{ current_soc?: { value: number; timestamp: string; source?: string }, local?: { planned_at?: string; planner_version?: string }, db?: { planned_at?: string; planner_version?: string } | { error?: string } }`
- `/api/forecast/horizon` → horizon lengths `{ pv_forecast_days?: number; weather_forecast_days?: number; ... }`

### Timezone & Slicing Notes
- Legacy: local timezone visuals; implicitly Europe/Stockholm.
- React: `formatHour` renders with `Intl.DateTimeFormat(..., timeZone: 'Europe/Stockholm')`. However, `isToday`/`isTomorrow` rely on `toISOString().slice(0,10)` (UTC), which can misclassify slots around local midnight and during DST shifts. Action: base day comparisons on local TZ instead of UTC.

## Planning — Timeline Interactions
- Legacy: vis-timeline with lanes (Battery/Water/Export/Hold), lane-aligned `+ chg/+ wtr/+ exp/+ hld` buttons, drag/resize, simulate→save, historical slots read-only, device caps enforced, SoC target semantics respected.
- React: Static mock lanes/blocks; no vis-timeline, no interactions, no API wiring.
- Gaps:
  - Integrate vis-timeline into React and style with new theme
  - Implement create/edit/delete of manual blocks
  - Wire `/api/simulate` for preview and `/api/schedule/save` for persistence
  - Refresh chart after changes; handle historical/read-only and zero-capacity gaps

### Planning Endpoints & Contracts
- `/api/simulate` (POST): merge manual blocks into optimal plan for preview; returns schedule in same shape as `/api/schedule` (confirm payload contract from backend)
- `/api/schedule/save` (POST): persist manual plan to local/server plan

## Settings
- Legacy: Form-based configuration panels (decision thresholds, battery economics, charging strategy, strategic charging, etc.) using `/api/config`, `/api/config/save`, `/api/config/reset`.
- React: Placeholder page; no forms.
- Gaps:
  - Build form UI mapped to nested config keys; validate and post to `/api/config/save`
  - Render current config from `/api/config`; support reset

## Themes
- Legacy: `/api/themes` and `/api/theme` to list/set theme and accent; themes folder supports JSON/YAML/legacy formats with validation; UI can change theme and accent index.
- React: No theme picker yet; Tailwind tokens are static.
- Gaps:
  - Implement theme selection UI and post to `/api/theme`
  - Optionally map theme palette into Tailwind CSS variables (or hydrate CSS vars at runtime)

## Learning & Debug
- Legacy: Learning: `/api/learning/status`, `/api/learning/loops`, `/api/learning/changes`; Debug: `/api/debug`, `/api/debug/logs` (ring-buffered), plus `/api/history/soc`.
- React: Placeholder pages; no data calls.
- Gaps:
  - Implement metrics/tables/cards; logs viewer with polling; history chart as needed

## Quick Actions
- Legacy controls: Run planner, load server plan, push to DB, apply manual changes, reset to optimal.
  - `/api/run_planner` (POST)
  - `/api/db/current_schedule` (GET)
  - `/api/db/push_current` (POST)
  - `/api/schedule/save` (POST) and reset behavior (clear manual deltas)
- React: Buttons present, not wired.
- Gaps:
  - Wire buttons to these endpoints and refresh state/chart accordingly

## Production Serving
- Legacy: Flask serves UI and APIs.
- React: Dev proxy for `/api` via Vite; build output not yet served by Flask in production.
- Gaps:
  - Decide on deploy pattern: serve `frontend/dist` from Flask or separate static host; add Flask static route if needed

---

## Risks & Issues
- Timezone day slicing correctness (UTC vs local midnight, DST transitions)
- Consistency of dataset semantics (kW vs kWh bars/lines; visibility and stacking behaviors)
- Manual planning semantics (device caps, SoC guardrails) must match backend logic
- Duplicated legacy files at repo root vs `backend/` for tests/imports (organizational risk)

---

## Recommended Steps (Backlog Overview)
1. Dashboard polish
   - Fix local day slicing; add dataset toggles and status/horizon badges
2. Timeline (vis-timeline) integration
   - Integrate component; CRUD flows; simulate→save; chart sync; stylistic parity
3. Quick actions wiring
   - Run planner, load server plan, push to DB, reset optimal
4. Learning & Debug
   - Data calls + UI; logs polling; optional mini charts
5. Settings & Theme
   - Config forms; theme picker using `/api/themes` + `/api/theme`
6. Production serving
   - Decide deployment, add Flask static serving if required

