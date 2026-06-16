## Context

The battery cycle cost is a fixed physical cost (battery price ÷ lifetime throughput). Today three things conflate it with behavior:

1. **Reflex `analyze_roi`** rewrites `config.yaml`, drifting `battery_economics.battery_cycle_cost_kwh` toward realized 30-day arbitrage profit (bounded 0.1–0.5, ±0.05/day). This is circular — profitability should change *behavior*, not the *cost input*.
2. **StrategyEngine** overrides the solver's `wear_cost_sek_per_kwh` per-plan based on price spread, going to `0.0` on volatile days — modelling the battery as free.
3. The **Grid & Financial card** shows only pure grid cash (`net_cost_sek`), so battery wear is invisible to the user.

The data needed to surface wear already exists: `/api/energy/range` already aggregates `battery_charge_kwh` and `battery_discharge_kwh` per period, and the cycle cost is in config. The wear model is the solver's own: `(charge + discharge) × cost × 0.5`.

## Goals / Non-Goals

**Goals:**
- Make `battery_cycle_cost_kwh` user-owned: never auto-modified by the learning engine.
- Guarantee the configured cycle cost is a hard floor on the solver's wear cost (StrategyEngine may only raise it).
- Show battery wear on the Grid & Financial card without changing the established headline Net.
- Keep it KISS and production-grade: minimal surface, single source of truth.

**Non-Goals:**
- Re-tuning the StrategyEngine volatility curve (no additive-margin redesign).
- Introducing a separate "arbitrage aggressiveness" parameter (decided against — StrategyEngine already adapts behavior).
- Any DB/schema change, new recorder fields, or capex tracking.
- Resetting whatever value currently sits in `config.yaml` (out of scope per direction).

## Decisions

**1. Remove the ROI analyzer outright rather than leave it dormant.**
Dead code rots and the premise (cost = profit) is wrong. Removing `analyze_roi`, dropping its `BOUNDS`/`MAX_DAILY_CHANGE` entries, and removing it from the orchestration loop is cleaner than gating it. The capacity analyzer (fade → `battery.capacity_kwh`) is untouched. *Alternative considered:* a config flag to disable it — rejected as needless surface for logic that should not exist.

**2. Clamp, not additive margin, for the floor.**
Effective wear = `max(battery_cycle_cost_kwh, resolved_value)`. This is the minimal change, keeps the existing StrategyEngine 0.0–1.0 curve untouched, and guarantees the floor. *Alternative considered:* treat the override as a margin added on top of cost — rejected: requires re-tuning the strategy numbers and carries regression risk, against KISS.

**3. Enforce the floor at one place — the solver adapter (SSOT).**
The adapter (`config_to_kepler_config` in `planner/solver/adapter.py`) is the single point where `wear_cost_sek_per_kwh` is finalized from overrides/config/default. Applying `max(cycle_cost, …)` there means the floor holds no matter who set the value. *Alternative considered:* clamping inside the StrategyEngine — rejected: leaves other code paths (root-level config, default) unprotected and splits the invariant.

**4. Card: secondary line + breakdown row, headline untouched.**
`net_cost_sek` (real cash) stays the headline. The endpoint computes `battery_wear_cost_sek` and `net_cost_incl_wear_sek`; the card adds a distinct secondary "incl. battery wear" line and a "Battery Wear" breakdown row. Wear is a modelled estimate, so it is shown beside — never folded into — the measured cash figure. *Alternative considered:* fold wear into the headline Net — rejected: silently redefines a number users already track and mixes measured cash with an estimate.

**5. Compute wear in the backend endpoint, not the frontend.**
Keeps the formula and the config read server-side (one place), so the card just renders fields. Consistent with the existing endpoint that already returns all other financial figures.

## Risks / Trade-offs

- **Behavior shift on volatile days** → On high-spread days the solver previously saw wear `0.0`; now it sees the cycle cost (e.g. 0.2), so it cycles marginally less aggressively. This is the intended correction, not a regression. Mitigation: it is bounded and small; verify a plan on a high-spread day still behaves sensibly.
- **Historical-period wear uses the current config rate** → For week/month periods, wear applies today's rate to past throughput. Since the rate is now fixed (not drifting), this is consistent and defensible; no per-slot rate storage needed. No mitigation required.
- **Removing `analyze_roi` may leave an unused helper** → `get_arbitrage_stats` may become unused after removal. Mitigation: check call sites; remove if orphaned, leave if still used elsewhere (e.g. an ROI display).
- **Sign/label clarity on the card** → "incl. battery wear" must read clearly as cost-inclusive. Mitigation: reuse the existing color/sign convention; label the breakdown row "Battery Wear".

## Migration Plan

1. Backend: add `battery_wear_cost_sek` / `net_cost_incl_wear_sek` to the energy endpoint response (purely additive — safe for existing clients).
2. Adapter: apply the `max(cycle_cost, …)` clamp at the wear-cost resolution point.
3. Reflex: remove `analyze_roi`, its bounds/rate-limit entries, and its orchestration call; update the `reflex_enabled` config comment to drop "battery cost".
4. Frontend: add the secondary line and breakdown row.
5. Verify: high-spread plan respects the floor; energy endpoint returns correct wear; card renders both new elements; a Reflex run leaves `battery_cycle_cost_kwh` untouched.

Rollback: changes are independent and additive; revert any single step without affecting the others.

## Open Questions

None — clamp mechanism, SSOT enforcement point, removal-vs-dormant, and card layout are all decided.
