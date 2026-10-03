## Why

The Grid & Financial card shows "x% solar" for EV charging that happened at night. The solar share is computed as the EV energy not covered by grid import in the same slot (`ev − min(ev, import)`); `pv_kwh` is never read. EV energy and grid import are measured independently, and any per-slot disagreement between them is reported as solar. Production data shows this at 00:15 and 01:30 on 2026-10-01 (PV = 0, battery idle, "solar" 0.14 and 0.61 kWh). The label makes a claim the number cannot support.

## What Changes

- Attribute EV solar energy from measured PV: per slot, `ev_solar_kwh = min(ev_charging_kwh, max(0, pv_kwh − load_kwh − water_kwh))`, the PV surplus left after house base load and water heating. Zero PV means zero solar.
- `ev_grid_kwh = ev_charging_kwh − ev_solar_kwh`, so grid plus solar still equals recorded EV energy. Remove the "grid first, capped at import" rule.
- EV cost per slot uses `min(ev_grid_kwh, import_kwh) × import_price_sek_kwh`, so the period EV cost stays a subset of `import_cost_sek`.
- `ev_solar_share` keeps its definition (`Σ ev_solar_kwh / Σ ev_charging_kwh`) and its informational role. No API field, UI or tooltip change.
- Known simplification, documented in the spec: battery charging is not subtracted from the PV surplus, so the solar share is an upper bound when the battery is charging from solar at the same time as the EV.

Independent of `recorder-slot-aligned-energy`, which fixes the per-slot timing of `import_kwh` and the other recorded energies. This change is correct on its own; the recorder change removes the remaining under-costing in charge-start slots.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `ev-cost-attribution`: solar is bounded by measured PV surplus, grid is the remainder, cost is capped at the slot's import. `energy-totals-api` needs no delta: it already defers to this capability and its "cost SHALL NOT exceed `import_cost_sek`" guarantee still holds.

## Impact

- `backend/api/routers/energy.py` (EV attribution SQL expressions, ~lines 232-236, 276-280).
- `openspec/specs/ev-cost-attribution/spec.md`.
- Backend tests for the energy router attribution.
- No schema change, no new dependency, no frontend change. Historical periods recompute on read, so past days change too (night charging drops to 0% solar).
