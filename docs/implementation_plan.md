# THIS PLAN SUPERSEEDS THE "PROJECT_PLAN_Vx.MD"! ONLY USE THOSE AS REFERENCE!

# Implementation Plan: Darkstar Planner Parity

## Change Log
- **2025-11-02 (Rev 7)**: Updated SoC clamp semantics (no forced drop), expanded water-heating horizon (next midnight + deferral), added charge block consolidation with tolerance/gap controls, fixed timeline block length, added UI SoC validation, and extended tests (46 pass, 4 skipped).
- **2025-11-02 (Rev 6)**: UI theme system implemented — scan `/themes`, expose Appearance dropdown, persist selection, apply CSS variables/palette to charts & buttons, add tests.
- **2025-11-02 (Rev 5 — Plan)**: Upcoming fixes: grid-only water heating in cheap windows, remove PV export planning, peak-only battery export with responsibility guard, configurable export percentile, disable battery-for-water in cheap windows, extend PV + weather forecast horizon to 4 days, UI settings and chart export series.
- **2025-11-02 (Rev 4)**: Integrated Home Assistant SoC + water stats, dynamic S-index (PV deficit & temperature), web UI updates, and new HA/test coverage.
- **2025-11-02 (Rev 3)**: Future-only MPC with water deferral window; removed price duplication; S-index surfaced in UI; HA timestamp fixes; discharge/export rate limits; planner telemetry debug persisted to sqlite; tests updated (42 pass).
- **2025-11-01 (Rev 1)**: Implemented Phases 1-5 - by Grok Code Fast 1.
- **Initial (Rev 0)**: Plan created - by GPT-5 Medium after gap analysis.

## Goals
- Achieve feature and behavioural parity with Helios `decision_maker.js` while respecting Darkstar architecture.
- Provide robust configuration, observability, and test coverage supporting future enhancements (S-index calculator, learning engine, peak shaving).
- Deliver changes in severity/impact order to minimise regressions.

## Non-Goals
- Building the S-index calculator or full learning engine (tracked as backlog).
- External database migrations (sqlite only for now).
- Emissions-weighted optimisation or advanced demand-charge handling beyond backlog items.

## Key Assumptions
- Configurable parameters must be surfaced in `config.yaml` and reflected in the web-app settings/system menus.
- Battery BMS enforces absolute SoC limits (0–100%); planner respects configured min/max targets (default 15–95%).
- Export price equals grid import price (no built-in fees beyond configurable overrides).
- Water heating usage data from Home Assistant may be unavailable; internal tracker must provide a reliable fallback resetting at local midnight (Europe/Stockholm).

## Phase Breakdown (Severity-Ordered)

### Phase 1 – Correctness Foundations (Severity 1) ✅ COMPLETED
1. **Round-trip efficiency fix** ✅
   - Introduce helper functions using `sqrt(roundtrip_efficiency)` for charge/discharge energy conversions.
   - Update `_pass_3`, `_pass_6`, and `simulate_schedule` to use new helpers.
   - Config: add `battery.roundtrip_efficiency_percent` (default 95.0).
   - Tests: verify a full cycle loses expected energy.

2. **Battery cost accounting & wear** ✅
   - Maintain `total_kwh` and `total_cost` for battery state; update on charge/discharge/export.
   - Introduce `battery_economics.battery_cycle_cost_kwh` (default 0.20) and include in profitability comparisons.
   - Update decision thresholds (load cover, water, export) to incorporate wear cost.
   - UI: display battery average cost on dashboard.
   - Tests: weighted average correctness; wear reflected in decision thresholds.

### Phase 2 – Realistic Slot Constraints & Responsibilities (Severity 2–3) ✅ COMPLETED
3. **Slot-level power limits** ✅
   - Compute available charge power per slot considering inverter limit, grid limit, concurrent water heating, and net load.
   - Update Pass 5 distribution and execution.

4. **Gap responsibilities with price thresholds** ✅
   - Store window start states (SoC, cost) during depletion pass.
   - Compute gap energy only for slots where `import_price > avg_cost + wear + battery_use_margin`.
   - Apply S-index factor (static for now); add `s_index` config block.
   - Update cascading inheritance to include window self-depletion.
   - Tests: responsibilities scale with S-index and price filters.

### Phase 3 – Water Heating Parity (Severity 4) ✅ COMPLETED
5. **Schedule contiguous blocks** ✅
   - Parameters: `water_heating.min_hours_per_day`, `min_kwh_per_day`, `max_blocks_per_day`, `schedule_future_only`.
   - Prefer a single block; allow two when required to meet minimum energy/time; do not plan extra slots once `min_kwh` met for today.
   - Respect existing scheduled slots (no removal of already executed blocks).

6. **Source selection & tracking** ✅
   - Execution order: PV surplus → battery (economical) → grid.
   - Update slot flows (`water_from_pv`, `water_from_battery`, `water_from_grid`).
   - Integrate HA sensor when provided; otherwise refresh sqlite tracker at midnight.
   - Tests: ensure single/two block scheduling; verify fallback tracker increments.

### Phase 4 – Export & Strategic Enhancements (Severity 5–6) ✅ COMPLETED
7. **Export logic & protective SoC** ✅
   - Config: `arbitrage.enable_export`, `export_fees_sek_per_kwh`, `export_profit_margin_sek`, `protective_soc_strategy`, `fixed_protective_soc_percent`.
   - Compute protective SoC from future responsibilities (gap-based) or fixed fallback.
   - Execute export when profitable and safe; update flows and costs.

8. **Strategic windows and carry-forward** ✅
   - Mark strategic windows for slots below `strategic_charging.price_threshold_sek` when PV deficit predicted.
   - Add `carry_forward_tolerance_ratio` to extend strategic tagging when SoC below target.
   - Ensure strategic target ties to `battery.max_soc_percent` (default 95).
   - Tests: strategic windows propagate until SoC target reached.

### Phase 5 – Smoothing, Observability, and Schema (Severity 7–9) ✅ COMPLETED
9. **Smoothing & hysteresis** ✅
   - Config: `smoothing.price_smoothing_sek_kwh`, `min_on/off` slots per action.
   - Extend cheap slot admission using smoothing tolerance.
   - Add final pass to enforce action block lengths without violating safety.
   - Tests: single-slot toggles are eliminated when constraints allow.

10. **Output schema & debug parity** ✅
    - Rename classifications to lowercase; add flows, projected costs, reasons, priorities.
    - Optional debug payload (configurable) containing windows, gaps, charging plan, water analysis, metrics.
    - Tests: JSON schema validation; debug toggle.

### Phase 6 – Tooling & Documentation (Severity 10) ✅ COMPLETED
11. **Testing suite expansion** ✅
   - Energy/cost conversion helpers: 6 tests covering efficiency calculations, cycle costs, edge cases.
   - Water block scheduling: 5 tests covering contiguous blocks, single vs multiple block preference, future day scheduling.
   - Gap responsibility calculations: 6 tests covering price-aware gaps, S-index factors, cascading inheritance, strategic overrides.
   - Export protective SoC logic: 8 tests covering profitability decisions, protective SoC calculations, energy limits, state updates.
   - Hysteresis/smoothing behaviour: 7 tests covering minimum block enforcement, recent activity extension, multiple action types.
   - schedule.json schema check: 5 tests covering basic schema, lowercase classifications, reason/priority fields, numeric rounding, debug payload structure.
   - **Total: 39 comprehensive tests** with 100% pass rate, covering all core functionality and edge cases.

12. **Documentation & migration**
    - Update README, AGENTS.md with new config keys and testing instructions.
    - Provide migration notes for existing configs (default additions, renames).

## Configuration Schema Additions
| Section | Key | Default | Notes |
| ------- | --- | ------- | ----- |
| `battery` | `roundtrip_efficiency_percent` | 95.0 | Preferred over `efficiency_percent`. |
|  | `max_soc_percent` | 95 | Planner target ceiling (BMS still caps at 100). |
| `battery_economics` | `battery_cycle_cost_kwh` | 0.20 | Wear cost per discharged kWh. |
| `decision_thresholds` | `export_profit_margin_sek` | 0.05 | Minimum extra profit for export. |
| `charging_strategy` | `price_smoothing_sek_kwh` | 0.05 | Smoothing tolerance for blocks. |
|  | `block_consolidation_tolerance_sek` | 0.05 | Additional tolerance for merging charge blocks (falls back to smoothing when unset). |
|  | `consolidation_max_gap_slots` | 0 | Number of zero-capacity slots allowed while treating a block as contiguous. |
| `strategic_charging` | `carry_forward_tolerance_ratio` | 0.10 | For strategic propagation. |
| `water_heating` | `min_hours_per_day` | 2.0 | Required runtime per day. |
|  | `min_kwh_per_day` | derived | Falls back to `min_hours_per_day × power_kw` when unset. |
|  | `max_blocks_per_day` | 2 | Scheduler prefers 1 block; allows breaking into two. |
|  | `schedule_future_only` | true | Avoids scheduling current slot. |
| `arbitrage` | `enable_export` | true | Master toggle. |
|  | `export_fees_sek_per_kwh` | 0.0 | Adjust if operator charges fees. |
|  | `protective_soc_strategy` | `gap_based` | `fixed` alternative. |
|  | `fixed_protective_soc_percent` | 15.0 | Used when strategy = fixed. |
| `s_index` | `mode` | `static` | Calculator is backlog. |
|  | `static_factor` | 1.05 | Safety multiplier. |
|  | `max_factor` | 1.25 | Guardrail cap. |
| `smoothing` | `min_on_slots_charge` | 2 | Minimum consecutive charging slots. |
|  | `min_off_slots_charge` | 1 | Minimum off slots before restarting. |
|  | `min_on_slots_discharge` | 2 | As above for discharge. |
|  | `min_off_slots_discharge` | 1 |  |
|  | `min_on_slots_export` | 2 |  |
| `debug` | `enable_planner_debug` | false |  |
|  | `sample_size` | 30 | Number of slots to include in debug sample. |
| `learning` | `enable` | true | Controls sqlite logging. |
|  | `sqlite_path` | `data/planner_learning.db` | Storage location. |
|  | `sync_interval_minutes` | 5 | Aggregation cadence. |

## Web-App Updates
- **Battery Settings:** round-trip efficiency %, min/max SoC, cycle wear cost.
- **Strategy:** cheap percentile, price tolerance, smoothing tolerance, strategic threshold, target SoC, carry-forward tolerance.
- **Water Heating:** min hours/day, min kWh/day, power kW, max blocks/day, schedule future only.
- **Arbitrage/Export:** enable export, export fees, min profit, protective SoC strategy, fixed SoC.
- **Safety:** battery use margin, water margin, S-index mode/static factor.
- **Smoothing:** min on/off slots for charge/discharge/export.
- **Debug:** enable planner debug, sample size.
- **System Dashboard:** display battery average cost, water heating source breakdown, export summary, planner debug toggle.

## Data & Persistence Work
- Create sqlite database (`data/planner_learning.db`) storing:
  - `schedule_planned`
  - `realized_energy`
  - `daily_water`
- Provide migration script for initial schema with indices.
- Ensure planner writes realized water usage to sqlite (and reads HA sensor when available).

## Test Plan
1. **Unit Tests** (pytest)
   - Energy conversion helpers (charge/discharge).
   - Battery cost tracking with sequence of charges/discharges including wear.
   - Water block scheduler with fragmented cheap windows.
   - Price-aware responsibility calculation and inheritance.
   - Export protective SoC conditions.
   - Smoothing/hysteresis transformations.

2. **Integration Tests**
   - Simulated day scenarios (baseline, strategic period, negative price day) verifying schedule consistency.
   - Schema validation for `schedule.json`.
   - Debug enable/disable toggles.

3. **Manual Verification**
   - Web UI surfaces new settings and respects config.
   - sqlite file populated and resets water tracker at midnight.
   - Compare sample output to Helios reference for sanity (spot-check windows, exports, water blocks).

## Backlog Items
- **S-index calculator** – Use PV availability, load variance, temperature forecast to compute dynamic safety factor; integrate with responsibilities once validated.
- **Learning engine evolution** – Use recorded planned vs actual data to auto-adjust forecast margins and S-index; evaluate migration to MariaDB.
- **Peak shaving support** – Integrate demand charge constraints or monthly max power objectives.
- **Advanced analytics** – Historical rollups, planner telemetry dashboards, anomaly detection.

## Completion Summary

### ✅ Completed Phases
- **Phase 1 (Correctness Foundations)**: Round-trip efficiency and battery cost accounting implemented
- **Phase 2 (Realistic Slot Constraints)**: Slot-level power limits and price-aware gap responsibilities implemented
- **Phase 3 (Water Heating Parity)**: Contiguous block scheduling and source selection implemented
- **Phase 4 (Export & Strategic Enhancements)**: Export logic with protective SoC and strategic windows implemented
- **Phase 5 (Smoothing, Observability, and Schema)**: Hysteresis, debug payload, and enhanced output schema implemented
- **Phase 6 (Tooling & Documentation)**: Comprehensive test suite with 41 tests covering all functionality

### 🔄 Current Status
- **Phases 1-6**: Complete; focus shifts to backlog items and UI/QA follow-ups.

## Tracking & Delivery Checklist
- [x] Phase 1 changes merged with tests.
- [x] Phase 2 changes merged with tests.
- [x] Phase 3 changes merged with tests.
- [x] Config defaults updated in `config.default.yaml` and migrated in `config.yaml`.
- [x] Web-app settings updated; manual QA performed.
- [x] Docs (README, AGENTS) refreshed.
- [x] Planner debug output validated.
- [x] sqlite schema created and integrated.
- [ ] Backlog tickets filed for S-index calculator, learning engine, peak shaving.

## Change Management
- Roll out phases sequentially; monitor schedule outputs and logs between phases.
- Maintain `docs/implementation_plan.md` by ticking completed steps, adding links to PRs, and noting regressions or follow-up tasks.

---
_Last updated: 2025-11-01 (Phase 6 validated with telemetry + export fixes)_

## Rev 4 Plan: HA + Stats + Dynamic S-Index

Status: ✅ Completed 2025-11-02

Scope: Implement real SoC and water usage tracking from Home Assistant, expand Stats panel, and add a dynamic S-index that adapts to PV/load deficit and temperature forecasts.

Requirements
- [x] HA SoC
  - Source entity: `sensor.inverter_battery` (percentage).
  - Use as preferred source in `initial_state`: set `battery_soc_percent` and derive `battery_kwh` via capacity.
  - Fallback to existing config/state when HA unavailable.

- [x] Water usage today
  - Source entity: `sensor.vvb_energy_daily` (kWh).
  - Add API endpoint to expose today’s kWh; fallback to sqlite `daily_water.used_kwh` when HA not available.
  - Show “Water Heater Today” in Stats.

- [x] Stats panel
  - Show current SoC (from HA if available) and battery capacity.
  - Show S-index (mode/value/max). When dynamic mode is on, show computed value from planner debug payload.

- [x] Dynamic S-index
  - Config additions under `s_index`:
    - `mode: dynamic | static` (dynamic enabled by user).
    - `base_factor` (default 1.05), `max_factor` (cap, e.g., 1.50).
    - `pv_deficit_weight` (e.g., 0.30), `temp_weight` (e.g., 0.20).
    - `temp_baseline_c` (default 20), `temp_cold_c` (default -15).
    - `days_ahead_for_sindex`: list of day offsets to evaluate (default [2,3,4]).
  - Data: Use existing PV/load forecasts; fetch mean temp for D+2..D+4 from Open‑Meteo.
  - Algorithm (per day d in D+2..D+4):
    - Daily PV sum `pv_d`; daily load sum `load_d`; `def_d = max(0, (load_d - pv_d)/max(load_d, ε))`.
    - Average `avg_def = mean(def_d)`.
    - Temperature term: `temp_adj = clamp01((temp_baseline_c - t_mean)/ (temp_baseline_c - temp_cold_c))` (0 at baseline or warmer; 1 at/below cold).
    - Factor: `factor = base_factor + pv_deficit_weight*avg_def + temp_weight*temp_adj`, clamped to `max_factor`.
  - Integration: Use dynamic factor in Pass 4 where S-index is applied; fallback to static if data missing or mode=static.

Acceptance Criteria
- Planner uses HA SoC when available; Stats shows current SoC. ✅
- Stats shows “Water Heater Today: X.XX kWh” (HA or sqlite fallback). ✅
- S-index in Stats reflects mode/value; dynamic value matches computed factor. ✅
- Configurable deferral for water is preserved; planning remains future-only; no duplicated prices. ✅

Deliverables
- Code: inputs (HA reads), planner (dynamic S-index), webapp API for water usage today, stats UI tweaks. ✅
- Docs: Update README + AGENTS if needed; expand config.default.yaml with new s_index keys. ✅
- Tests: Unit tests for dynamic S-index calculation and HA integrations (mocked). ✅

Changelog/Versioning
- Suggested commit: `feat(planner): Rev 3 — future-only MPC, water deferral, no price duplication, S-index in UI`
- Suggested tag: `v0.3.0`

## Rev 5 Plan: Cheap-Window Water + Export Guards + Forecast Horizon

Status: ✅ Completed 2025-11-02

Summary: Strengthen MPC behavior around cheap windows, export decisions, and forecast coverage. Align export behavior with long-term savings by reserving energy for future needs and peak prices. Ensure 4-day horizons for PV and weather forecasts.

Scope of Changes
- Water heating source policy
  - In cheap windows, heat from Grid (not Battery). PV still used first when available.
  - Disable battery-for-water during cheap windows; grid covers the residual. Align with “hold in cheap windows”.

- Export policy
  - Remove explicit PV export planning. PV surplus still increases SoC; export happens only when battery is full due to physical constraints.
  - Battery export allowed only when ALL of the following are true:
    - Responsibilities fully covered to horizon (or SoC ≥ strategic target SoC), and
    - Slot price is in top X% (configurable export percentile), and
    - Net export price > (avg battery cost + wear + export margin), and
    - Optional guard: current export price ≥ max remaining import price in horizon − small buffer.

- Forecast horizon
  - Ensure PV forecast covers ≥ 4 days; otherwise fallback/dummy to fill coverage.
  - Fetch weather mean temperature for ≥ 4 days (Open‑Meteo daily); wire to dynamic S-index.
  - Stats panel shows “PV forecast: N days”, “Weather forecast: N days” (already added).

- UI
  - Add settings field: `arbitrage.export_percentile_threshold` (e.g., top 10–15%).
  - Add export series to chart so visible when export occurs.
  - Water-today label simplified (already done).

Config Additions
- `arbitrage.export_percentile_threshold` (default 15)
- Optional: `arbitrage.enable_peak_only_export` (default true)
- Optional: `arbitrage.export_future_price_guard` (bool) and `arbitrage.future_price_guard_buffer_sek` (default 0.0)

Implementation Tasks
- Planner (water heating):
  - In Pass 6, if `is_cheap` and `water_heating_kw > 0`: forbid battery contribution to water; use PV first, then grid.
  - Ensure net and SoC math reflects PV → battery → grid flows accurately.

- Planner (export):
  - Remove PV export planning path. Keep only battery export path.
  - Add peak-only export gate using `export_percentile_threshold` over horizon prices.
  - Add responsibilities/strategic coverage check (sum of `window_responsibilities` or current SoC ≥ target).
  - Optional forward-price guard as described.
  - Keep protective SoC as a lower bound; do not export below it.

- Forecast horizon:
  - PV: request or synthesize ≥ 4 days to map to all price slots in horizon.
  - Weather: fetch Open‑Meteo daily mean temperature for the full horizon (≥ 4 days). Use for dynamic S-index.

- UI/Settings:
  - Add `arbitrage.export_percentile_threshold` to Settings; persist on save.
  - Add “Export (kW)” series to chart.

Acceptance Criteria
- Water heating in cheap windows uses grid (PV first), never battery.
- No planned PV export actions; PV surplus only raises SoC. Exports still occur when battery is full (physical), but not planned.
- Battery export happens only in top-X% price slots and only when responsibilities covered (or SoC ≥ strategic target) and price thresholds hold. No midday export unless it is an actual local price peak and future needs are fully covered.
- Dynamic S-index still functions; export behavior respects protective SoC.
- Stats show PV/Weather forecast days ≥ 4 when upstream is healthy.
- Chart shows export bars/line when export occurs (so no “mystery” SoC drops).

Testing
- Unit tests:
  - Water heating source selection in cheap vs non-cheap windows; battery disallowed in cheap.
  - Export gating: peak-only, responsibilities satisfied, guard on price, and protective SoC.
  - No PV export planning; PV surplus storage only.
  - Forecast horizon reporting ≥ 4 days (mocked).
- Integration tests:
  - End-to-end scenarios: negative price day with PV; midday PV surplus with evening high price; check no battery export midday unless peak + reserved.

Changelog/Versioning
- Suggested commit after implementation: `feat(planner): Rev 5 — grid water in cheap windows, peak-only battery export, remove PV export planning, 4-day PV+weather horizon, UI settings and export series`
- Suggested tag: `v0.5.0`

## Rev 6 – UI Theme System (Completed 2025-11-02)

Status: ✅ Completed 2025-11-02

Highlights
- Theme discovery now scans `/themes` for JSON, YAML, or legacy key/value files. Invalid palettes are skipped with a console notice, and filenames (spaces preserved) become the display name.
- `GET /api/themes` returns `{ current, themes[] }`, and `POST /api/theme` persists the selected name under `ui.theme` inside `config.yaml`.
- Settings gained an “Appearance” fieldset with a dropdown sourced from `/api/themes`. Selection applies immediately (via CSS variables) and persists when saving configuration.
- Added palette accent selector (0–15) with persistence (`ui.theme_accent_index`) so the main colour used for tabs, stats borders, ASCII art, etc. can be tuned per theme.
- CSS moved to `--ds-*` variables for foreground/background, accents, and a 16-slot palette. Buttons use palette indices 8–15; charts/timeline actions draw from 0–7.
- Chart.js datasets derive colors from the active palette; gradients dynamically use theme colours, and tooltips adopt themed backgrounds. Timeline/manual blocks read CSS variables so theme swaps do not wipe manual edits.
- Timeline creation reuses a single vis.js instance (no duplicate charts on planner reruns) and auto-populates charge/water slots even when classifications are lowercased.

Implementation Notes
- `webapp.py`: added `_parse_legacy_theme_format`, `_normalise_theme`, and directory scanning helpers; injected `GET /api/themes` and `POST /api/theme` endpoints with config persistence.
- `templates/index.html`: appended the Appearance section and theme dropdown.
- `static/css/style.css`: replaced literal colours with `var(--ds-...)` references and provided a fallback palette for bootstrapping.
- `static/js/app.js`: introduced theme helpers (`applyThemeVariables`, `loadThemes`), wired dropdown events, re-coloured datasets, timeline styles, and ensured persisted selection survives resets.
- `tests/test_theme_system.py`: validates palette parsing/normalisation and confirms the API writes the chosen theme to `config.yaml` (restored post-test).

Testing
- Automated: `PYTHONPATH=. python -m pytest -q` → 43 passed, 4 skipped (theme system coverage included).
- Manual: Verified theme swap updates tabs, stats, buttons, chart datasets, timeline, and persists across reload + reset.

Changelog/Versioning
- Suggested commit: `feat(ui): Rev 6 — theme system with Appearance settings and palette application`
- Suggested tag: `v0.6.0`

## Rev 7 – SoC + Water Horizon + Charge Consolidation (Completed 2025-11-02)

Highlights
- SoC handling now respects the live state: charging is capped at `max_soc_percent`, but we no longer force an immediate clamp-down when the current SoC is higher (useful when HA reports > config max). Passes 3 & 6 only enforce the lower bound; pass 6 emits a warning when configs lag reality.
- Water heating uses a horizon of `next local midnight + defer_up_to_hours`, enabling scheduling into early tomorrow once prices are known. With `defer_up_to_hours = 0`, only today’s slots are considered.
- Charging consolidation rewrites window allocation to favour contiguous blocks while preserving total energy and slot-level limits. New config keys: `charging_strategy.block_consolidation_tolerance_sek` (default fallback to smoothing tolerance) and `charging_strategy.consolidation_max_gap_slots` (default 0).
- Timeline bars now use the block’s true end time, so multi-slot Charge/Water actions render at full duration.
- UI validation prevents invalid SoC limits (Min/Max % relationship) before saving; backend logs a warning if current SoC exceeds configured max.

Testing
- Added `tests/test_rev7_behaviour.py` covering SoC clamp behaviour, water-horizon deferral, and charge consolidation contiguity.
- Full suite: `PYTHONPATH=. python -m pytest -q` → **46 passed, 4 skipped**.

Changelog/Versioning
- Suggested commit: `feat(planner): Rev 7 — SoC clamp semantics, water horizon to next midnight, charge consolidation, timeline grouping fix`
- Suggested tag: `v0.7.0`
