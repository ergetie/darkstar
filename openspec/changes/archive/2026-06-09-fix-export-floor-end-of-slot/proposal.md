## Why

The export-floor SoC constraint is enforced on the **start-of-slot** SoC (`soc[t]`), but the battery discharges for the full slot before the floor is re-checked. This lets the solver run one extra full export slot past the floor: a slot that *starts* at the floor *ends* well below it. On a production system (66 kWh battery, 28% floor, ~16.5 kW discharge), a single 15-minute slot dumps ~4 kWh (~6% SoC), so the plan exports down to ~22% against a 28% floor — confirmed in a beta user's live schedule.

## What Changes

- Re-express the Kepler export-floor constraint to bind the **end-of-slot** SoC (`soc[t+1]`) instead of the start-of-slot SoC (`soc[t]`). When exporting in slot `t`, the SoC *after* that slot's discharge SHALL remain at or above the export floor.
- This lets the solver throttle export in the boundary slot so the battery lands exactly on the floor (rather than stopping a slot early), preserving export value while respecting the floor.
- Keep the existing soft formulation unchanged: the `is_exporting[t]` binary, the `export_floor_violation[t]` slack, and the `EXPORT_FLOOR_PENALTY` (1000 SEK/kWh) — only the SoC term the constraint references moves from `soc[t]` to `soc[t+1]`.
- Update the export-floor solver tests to assert end-of-slot behaviour (export must stop at the floor, not one slot below it).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `export-floor-constraint`: the floor is enforced on end-of-slot SoC (`soc[t+1]`) rather than start-of-slot SoC (`soc[t]`), so export can no longer drain the battery below the floor within a slot.

## Impact

- **Code**: `planner/solver/kepler.py` — the export-floor SoC constraint (~lines 453–457).
- **Tests**: `tests/planner/test_kepler_export_floor.py` — update/extend to assert end-of-slot SoC stays at or above the floor while exporting.
- **Behaviour**: planned export stops at the configured floor instead of overshooting by up to one slot. Most visible on large batteries with high discharge power. Self-consumption (non-export) discharge is unchanged — it still respects only `min_soc`.
- **No config or API changes.**
