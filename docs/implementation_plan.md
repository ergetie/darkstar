# Implementation Plan: Darkstar Planner Parity

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

### Phase 1 – Correctness Foundations (Severity 1)
1. **Round-trip efficiency fix**
   - Introduce helper functions using `sqrt(roundtrip_efficiency)` for charge/discharge energy conversions.
   - Update `_pass_3`, `_pass_6`, and `simulate_schedule` to use new helpers.
   - Config: add `battery.roundtrip_efficiency_percent` (default 95.0).
   - Tests: verify a full cycle loses expected energy.

2. **Battery cost accounting & wear**
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

### Phase 3 – Water Heating Parity (Severity 4)
5. **Schedule contiguous blocks**
   - Parameters: `water_heating.min_hours_per_day`, `min_kwh_per_day`, `max_blocks_per_day`, `schedule_future_only`.
   - Prefer a single block; allow two when required to meet minimum energy/time; do not plan extra slots once `min_kwh` met for today.
   - Respect existing scheduled slots (no removal of already executed blocks).

6. **Source selection & tracking**
   - Execution order: PV surplus → battery (economical) → grid.
   - Update slot flows (`water_from_pv`, `water_from_battery`, `water_from_grid`).
   - Integrate HA sensor when provided; otherwise refresh sqlite tracker at midnight.
   - Tests: ensure single/two block scheduling; verify fallback tracker increments.

### Phase 4 – Export & Strategic Enhancements (Severity 5–6)
7. **Export logic & protective SoC**
   - Config: `arbitrage.enable_export`, `export_fees_sek_per_kwh`, `export_profit_margin_sek`, `protective_soc_strategy`, `fixed_protective_soc_percent`.
   - Compute protective SoC from future responsibilities (gap-based) or fixed fallback.
   - Execute export when profitable and safe; update flows and costs.

8. **Strategic windows and carry-forward**
   - Mark strategic windows for slots below `strategic_charging.price_threshold_sek` when PV deficit predicted.
   - Add `carry_forward_tolerance_ratio` to extend strategic tagging when SoC below target.
   - Ensure strategic target ties to `battery.max_soc_percent` (default 95).
   - Tests: strategic windows propagate until SoC target reached.

### Phase 5 – Smoothing, Observability, and Schema (Severity 7–9)
9. **Smoothing & hysteresis**
   - Config: `smoothing.price_smoothing_sek_kwh`, `min_on/off` slots per action.
   - Extend cheap slot admission using smoothing tolerance.
   - Add final pass to enforce action block lengths without violating safety.
   - Tests: single-slot toggles are eliminated when constraints allow.

10. **Output schema & debug parity**
    - Rename classifications to lowercase; add flows, projected costs, reasons, priorities.
    - Optional debug payload (configurable) containing windows, gaps, charging plan, water analysis, metrics.
    - Tests: JSON schema validation; debug toggle.

### Phase 6 – Tooling & Documentation (Severity 10)
11. **Testing suite expansion**
    - Add pytest modules covering 
      - Energy/cost conversion helpers.
      - Water block scheduling.
      - Gap responsibility calculations.
      - Export protective SoC logic.
      - Hysteresis/smoothing behaviour.
      - schedule.json schema check.

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

## Tracking & Delivery Checklist
- [ ] Phase 1 changes merged with tests.
- [ ] Config defaults updated in `config.default.yaml` and migrated in `config.yaml`.
- [ ] Web-app settings updated; manual QA performed.
- [ ] Docs (README, AGENTS) refreshed.
- [ ] Planner debug output validated.
- [ ] sqlite schema created and integrated.
- [ ] Backlog tickets filed for S-index calculator, learning engine, peak shaving.

## Change Management
- Roll out phases sequentially; monitor schedule outputs and logs between phases.
- Maintain `docs/implementation_plan.md` by ticking completed steps, adding links to PRs, and noting regressions or follow-up tasks.

---
_Last updated: 2025-11-01_
