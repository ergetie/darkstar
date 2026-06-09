## Why

The Kepler MILP's inverter AC-limit constraint treats **all** PV as if it crosses the AC inverter (`discharge[t] <= max(0, inverter_ac_kwh - s.pv_kwh)`, i.e. `pv + discharge <= inverter_ac_kwh`). For DC-coupled hybrid inverters, PV charging the battery is a DC-to-DC path that never touches the AC boundary, so the constraint is physically wrong in two opposite ways: it is **over-restrictive** for battery charging (it can suppress valid plans where PV exceeds the AC rating and the excess should route to the battery — e.g. an 8 kW AC inverter with a 12 kWp array), yet it **fails to independently cap PV-to-AC** (load + export), so a plan can assume grid export above what the inverter can physically push out its AC side (stabilization-review finding #34).

## What Changes

- Split the single PV quantity in the solver into two routed flows per slot: `pv_to_battery[t]` (DC-coupled, bypasses the AC inverter) and `pv_to_ac[t]` (crosses the inverter to feed load/export), with a balance `pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh`.
- Replace the AC-limit constraint with `pv_to_ac[t] + discharge[t] <= inverter_ac_kwh`, so the limit governs only what actually crosses the AC side.
- Source battery charge from `pv_to_battery[t] + grid_import_to_battery[t]` (decide in design whether to split or preserve the existing `charge[t]` variable).
- Keep ramping, wear, and efficiency constraints operating on **total** charge/discharge, not per-path.
- Add (pending design) an `inverter.topology` config field (`dc_coupled` | `ac_coupled`) so AC-coupled systems — where battery charging also crosses the AC side — keep the stricter constraint. **BREAKING** only if the default topology assumption changes existing plans; the design phase will pick a backward-compatible default.

## Capabilities

### New Capabilities
<!-- none — this refines an existing planner constraint -->

### Modified Capabilities
- `planner`: the "Inverter AC constraint" requirement changes from capping `pv + discharge` to capping only `pv_to_ac + discharge`, introducing PV-routing decision variables and (optionally) topology-aware behavior.

## Impact

- **Code:** `planner/solver/kepler.py` (constraint + new decision variables around the existing `:431-434` AC-limit block; battery-charge sourcing); possibly `planner/solver/adapter.py` and `planner/solver/types.py` if a topology flag is threaded through.
- **Config:** potential new `inverter.topology` field (with migration default) — touches `config.default.yaml` and config validation/migration.
- **Tests:** `tests/planner/` solver tests covering the existing AC-limit scenarios must be updated for the new decision variables; add DC- vs AC-coupled cases.
- **No executor or recorder impact** — this is a planner physics-model refactor only. Hardware already clips real AC export, so the runtime risk today is over-optimistic export estimates and occasional suppressed-charge plans, not unsafe commands.
