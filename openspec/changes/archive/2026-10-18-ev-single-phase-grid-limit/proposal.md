# Proposal

## Why

Kepler only knows a total grid-import cap (`system.grid.max_power_kw`). With a single-phase EV charger and a hybrid inverter that grid-charges evenly across all three phases (Sungrow, confirmed by the maintainer), the planner stacks EV + battery grid charge + water heating inside the total cap but overloads the EV's phase and trips the main fuse. The runtime load balancer only reacts after the fact, and the EV then under-delivers against the plan. This partially addresses the BACKLOG item "[Planner] Per-Phase Load Awareness".

## What Changes

- Add a per-slot Kepler constraint, active only when `system.grid.main_fuse_a` is set and at least one plugged-in `type: current` EV charger uses fewer than 3 phases: the EV's line(s) must stay within the fuse margin, assuming all non-EV load (battery grid charge, water heating, house load, PV) is spread evenly over the 3 phases.
- Derive the limit from `system.grid.main_fuse_a x load_balancing.target_margin_percent / 100` (default 85%, same as the runtime balancer) and `system.grid.nominal_voltage_v`; no new settings.
- The existing total cap and soft `grid_import_limit_kw` are unchanged. 3-phase chargers, binary chargers and an unset `main_fuse_a` behave exactly as today.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `grid-power-limits`: planner additionally bounds the per-phase import on an EV charger's line(s) by the main fuse.

## Impact

- `planner/solver/types.py` (`KeplerConfig.max_phase_import_kw`, `EVChargerInput.phases`)
- `planner/solver/adapter.py` (populate both from config)
- `planner/solver/kepler.py` (new constraint next to the `max_import_power_kw` cap)
- New tests under `tests/planner/`
- No config schema/default changes, no DB, no UI, no dependencies. Not editing `docs/` (BACKLOG item is only partly addressed; maintainer decides later).
