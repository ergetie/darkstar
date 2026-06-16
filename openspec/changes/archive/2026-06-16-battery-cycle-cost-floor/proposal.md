## Why

The battery cycle cost (`battery_economics.battery_cycle_cost_kwh`) represents a fixed physical fact — battery price divided by lifetime throughput. Today it is treated as a tunable behavioral knob instead of a fixed cost: the Reflex ROI analyzer **rewrites the user's `config.yaml`** to drift it toward realized arbitrage profit, and the StrategyEngine can override it down to `0.0` on volatile days (telling the optimizer the battery is free). Meanwhile, none of this cost is ever shown to the user — the "Grid & Financial" card reports pure grid cash flow with battery wear invisible, so users cannot see whether arbitrage actually paid off after degradation.

## What Changes

- **Reflex stops owning the cycle cost.** The ROI analyzer is removed entirely; Reflex never reads, proposes, or writes `battery_economics.battery_cycle_cost_kwh`. The value is owned solely by config (the user). Capacity fade remains handled separately by the existing capacity analyzer. **BREAKING** (learning behavior): one Reflex tuning target is removed.
- **Cycle cost becomes a hard floor on solver wear cost.** At the single solver-adapter resolution point (SSOT), the wear cost passed to the solver is `max(battery_cycle_cost_kwh, strategy/override value)`. The StrategyEngine may demand *more* caution but can never push wear below the true cycle cost — the battery is never treated as free.
- **"Grid & Financial" card surfaces battery wear.** The energy endpoints expose a computed battery wear cost for the period; the card adds a secondary "incl. battery wear" net line under the headline and a "Battery Wear" row in the financial breakdown. The headline Net (real grid cash) is unchanged.

## Capabilities

### New Capabilities
- `battery-cost-integrity`: The battery cycle cost is a fixed, user-owned cost — never auto-modified by the learning engine.
- `grid-financial-wear-display`: The Grid & Financial card displays battery wear cost (secondary net line + breakdown row).

### Modified Capabilities
- `planner`: The solver's wear cost is clamped so the configured battery cycle cost is always a hard floor (StrategyEngine overrides may only raise it).
- `energy-totals-api`: Energy endpoints return a computed `battery_wear_cost_sek` (and net-including-wear) for the period.

## Impact

- **Removed:** `analyze_roi` in `backend/learning/reflex.py`; `battery_economics.battery_cycle_cost_kwh` entries in Reflex `BOUNDS` / `MAX_DAILY_CHANGE`; its mention in the `reflex_enabled` config comment.
- **Modified:** `planner/solver/adapter.py` (clamp wear cost to the configured floor at the single resolution point); `backend/api/routers/energy.py` (compute and return battery wear cost); `frontend/src/components/CommandDomains.tsx` (Grid & Financial card display).
- **Data source:** uses existing `battery_charge_kwh` / `battery_discharge_kwh` already aggregated by the energy endpoint — no DB/schema change, no new recorder fields.
- **Config:** `battery_economics.battery_cycle_cost_kwh` semantics unchanged; it simply stops being auto-written.
