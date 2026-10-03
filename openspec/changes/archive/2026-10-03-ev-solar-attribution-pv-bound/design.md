## Context

`ev-cost-attribution` splits each slot's EV energy as `grid = min(ev, import)`, `solar = ev − grid`. The "solar" bucket is a residual: anything the grid meter did not account for in the same slot. EV energy comes from exact-window integration of the charger's power history, while `import_kwh` comes from a cumulative inverter counter that updates about every 10 minutes at 0.1 kWh resolution (see `recorder-slot-aligned-energy`). In charge-start slots the counter lags, the residual becomes positive, and it is shown as solar. Verified on production for 2026-10-01 00:15 and 01:30: PV = 0, battery idle (discharge 0, SoC flat), "solar" 0.14 and 0.61 kWh.

The aggregation is a single SQL query in `backend/api/routers/energy.py` that computes the per-slot expressions and sums them; there is no stored attribution column.

## Goals / Non-Goals

**Goals:**
- Solar share can only be non-zero when PV was actually produced and not consumed by the house.
- Keep `ev_grid_kwh + ev_solar_kwh = ev_charging_kwh` and `ev_cost_sek ≤ import_cost_sek`.
- No API, schema or frontend change.

**Non-Goals:**
- Fixing the per-slot timing of recorded energies (`recorder-slot-aligned-energy`).
- Modelling battery charging vs EV competition for PV, or a battery-to-EV source (the battery does not discharge to the EV; measured discharge was 0).
- Changing how the UI labels or explains the share.

## Decisions

**1. Solar is bounded by PV surplus, not by `pv_kwh` alone.** `surplus = max(0, pv − load − water)`, where `load_kwh` is already base load with EV and water removed (recorder base-load isolation). Alternative `min(ev, pv)` is simpler but claims solar for energy the house itself consumed. Surplus is a tighter, still cheap bound.

**2. Grid is the remainder (`ev − solar`), not `min(ev, import)`.** This makes the split conserve energy regardless of how well `import_kwh` is measured and removes the dependence on the lagging counter. Alternative "solar first, grid capped at import" leaves an unattributed gap in charge-start slots, which breaks the `grid + solar = ev` contract.

**3. Cost keeps the import cap per slot.** `min(ev_grid, import) × price` preserves the existing guarantee that EV cost is a subset of import cost. In charge-start slots where import is still under-recorded this slightly under-costs the EV; `recorder-slot-aligned-energy` removes that residual. Alternative of dropping the cap would let `ev_cost_sek` exceed `import_cost_sek` on a lagging slot.

**4. Battery charging is not subtracted from surplus.** There is no per-slot record of where battery charge came from, so the share is documented as an upper bound. Alternative of subtracting `batt_charge_kwh` would wrongly zero solar when the battery is charged from the grid in the same slot.

## Risks / Trade-offs

- [Historical periods change on read: night charging now shows 0% solar, daytime shares change] → Intended; no stored values to migrate. Mention in release notes only if the user asks.
- [`load_kwh` is clamped to 0 when EV exceeds total load (13 recorder warnings in the last week), which can overstate surplus] → Only matters when `pv_kwh > 0`; night slots are unaffected. Fully resolved by `recorder-slot-aligned-energy`.
- [Existing tests encode the old split (`test_night_charging_is_all_grid` passes only by coincidence; `test_midday_partial_solar` and the null-input test assert the old residual)] → Rewrite them to the new scenarios.

## Migration Plan

Pure read-path change; deploy normally. Rollback is reverting the query.

## Open Questions

None.
