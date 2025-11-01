# Gap Analysis: Darkstar Planner vs Helios Decision Maker

## Scope
- Compare current Python planner implementation (`planner.py`) with legacy Helios JavaScript planner (`decision_maker.js`).
- Highlight behavioural gaps, bugs, missing configuration, and observability differences.
- Prioritise findings by severity/impact.

## Summary of Findings
1. **Critical energy accounting bugs** – Round-trip efficiency handled incorrectly and battery average cost drift risk (`planner.py:203`, `planner.py:405`).
2. **Missing degradation economics** – Decisions ignore cycle wear cost that Helios implicitly budgeted via thresholds and dynamic averages (`decision_maker.js:802`).
3. **Water heating parity incomplete** – Scheduling ignores real usage state, prefers scattered slots, and runtime source selection is simplistic compared to PV > battery > grid logic (`planner.py:145`, `decision_maker.js:783`).
4. **No export/protective logic** – Python planner cannot monetise exports and lacks protective SoC reserve, unlike Helios (`decision_maker.js:947`).
5. **Responsibility modelling simplified** – Current cascading logic ignores price thresholds, S-index safety, and self-depletion, leading to potential under-charging before expensive periods (`planner.py:292`, `decision_maker.js:331`).
6. **Charging plan not capacity-aware** – Ignores inverter limits, concurrent loads, and water heating draw when assigning charge power; Helios computes real available kW per slot (`planner.py:349`, `decision_maker.js:627`).
7. **Strategic carry-forward absent** – Strategic windows do not propagate when target SoC unmet (`planner.py:303`, `decision_maker.js:544`).
8. **No smoothing/hysteresis or block planning** – Leads to noisy on/off behaviour versus Helios’ price smoothing and min block lengths (`decision_maker.js:603`).
9. **Config & UI coverage gaps** – Several Helios parameters are missing or renamed, preventing parity control from the web app.
10. **Observability gaps** – Python schedule lacks detailed flows, reasons, and debug traces available in Helios (`decision_maker.js:1004`).

## Detailed Gap Catalogue

### 1. Battery Efficiency & Cost (Severity: Critical)
- Discharge removes `deficit_kwh / efficiency` instead of using `sqrt(eff)`; charge adds `surplus_kwh * efficiency`, making round-trip ≈100%.
- Average cost update divides by `(current_kwh + charge_kwh)` after `current_kwh` already includes the new charge, overstating denominator.
- Impact: System overestimates stored energy, underestimates cost, and may discharge when unprofitable.

### 2. Degradation & Profit Thresholds (Severity: Critical)
- No configurable wear cost per kWh cycle; Helios uses explicit margin checks and dynamic cost tracking.
- Implication: Planner may over-cycle battery for marginal spreads, shortening life.

### 3. Water Heating Logic (Severity: High)
- Hardcoded `daily_water_kwh_today = 0.5`; lacks HA sensor integration and fallback tracker.
- Scheduling picks cheapest individual slots, not contiguous blocks; maximum blocks per day not enforced.
- Execution always consumes full `water_heating_kw` via net load; no PV/battery/grid prioritisation.
- Helios monitors actual energy, schedules 1–2 future blocks, and chooses source per slot.

### 4. Export & Protective SoC (Severity: High)
- No export branch, no protective SoC derived from future gaps, no export profitability check.
- Helios exports when profitable and safe using protective reserve based on responsibilities.

### 5. Cascading Responsibilities (Severity: High)
- Responsibility equals `min_soc_kwh - min_soc_until_next`, regardless of price or availability.
- No S-index multiplication, dynamic battery cost projection, or window self-depletion adjustment.
- Helios calculates gap energy only where battery is economical, scales by S-index, and adds depletion & inheritance fixes.

### 6. Charging Distribution (Severity: High)
- Assigns max charge power to sorted slots without checking inverter limits, concurrent water heating, or net load.
- Helios computes available power each slot, net battery gain (accounting for water discharge), and adds slots until target SoC met.

### 7. Strategic Windows & Carry-Forward (Severity: Medium)
- Python marks strategic windows but does not propagate when target unmet; no tolerance factor.
- Helios marks subsequent cheap windows strategic when still below target and price acceptable.

### 8. Smoothing & Hysteresis (Severity: Medium)
- No smoothing tolerance or minimum on/off durations; results in chattery charge/discharge actions.
- Helios applies price smoothing, SoC-target iteration, and blockisation.

### 9. Config & Settings Coverage (Severity: Medium)
- Missing parameters: round-trip efficiency, cycle cost, export fees/profit margin, price smoothing, carry-forward tolerance, max water blocks, protective strategies, hysteresis, debug toggles.
- Water heating config requires new `min_kwh_per_day`, `min_hours_per_day`, `max_blocks_per_day`, `schedule_future_only`.

### 10. Observability & Debug (Severity: Low)
- schedule.json lacks grid flows, water source breakdown, projected costs, decision reasons/priorities, debug summary.
- Harder to validate planner correctness or visualise contributions.

### 11. Learning & S-Index (Backlog)
- No learning engine recording planned vs actual; Helios planned for a data-driven feedback loop.
- S-index currently fixed; calculator should consider PV availability, load variance, temperature forecast.

## Configuration Mismatches
- `strategic_charging.price_threshold_sek` vs Helios `decision_thresholds.strategic_price_threshold`.
- Missing `battery.roundtrip_efficiency_percent`, `battery_cycle_cost_kwh`, `smoothing.price_smoothing_sek_kwh`, `arbitrage.*`.
- Water heating keys not aligned (`daily_minimum_kwh` vs proposed `min_kwh_per_day`).

## Testing Gaps
- No automated coverage for efficiency math, water scheduling, gap allocations, export, or schema validation.
- Need tests for block planning, hysteresis, and config toggles.

## Observability & Tooling
- Add optional debug artefacts mirroring Helios: window states, gap allocations, charging plan, water analysis, action summary.
- Include sqlite-based logging for planned vs actual to support future learning engine.

## Recommendations (High-Level)
1. Implement corrected energy/cost accounting with cycle wear cost parameter.
2. Rebuild water heating and charging passes to respect contiguous blocks, realistic power limits, and source priorities.
3. Introduce export logic, protective reserves, and price-aware responsibilities with S-index scaffolding.
4. Expand configuration schema and web UI to expose all planner knobs.
5. Add smoothing/hysteresis, debug outputs, and regression tests for new behaviours.

## Backlog Items
- **S-index calculator** – Use PV availability, load variance, temperature forecast; integrate with responsibilities once designed.
- **Learning engine** – Persist planned vs realised (sqlite initially, MariaDB later); adjust configuration automatically.
- **Peak shaving support** – Consider demand charge/maximum power limits in optimisation.

---
_Last updated: 2025-11-01_
