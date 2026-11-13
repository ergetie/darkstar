# Proposal

## Why

A water heater (VVB) wired to one phase is invisible to the planner's per-phase fuse limit. Real prod case: 16 A main fuse, a 3 kW single-phase water heater on L3. The planner schedules EV charging at the same time, L3 overloads, and the load balancer pauses the EV. Today the heater's phase lives only in `load_balancing.loads[].phases`, which the planner never reads, and it only exists once the user has configured load balancing. A heater's wiring is a property of the device, so it should live on the device and be read by both the planner and the balancer.

## What Changes

- New per-device setting `water_heaters[].phases` (list of 1-3, default `[1, 2, 3]` = spread evenly = current behaviour). Single source of truth for a water heater's phases.
- Load balancer reads the phase(s) of `water_heater` shed loads from `water_heaters[]` (matched by `device_id == id`), not from `loads[].phases`. `custom_entity` loads keep their own `phases`. EV chargers keep `ev_chargers[].phases`.
- Config migration moves existing `load_balancing.loads[].phases` of `water_heater` entries onto the matching `water_heaters[]` device, then removes it from the load entry.
- Planner (Kepler): the per-phase fuse constraint (`max_phase_import_kw` = main fuse x load-balancing margin) now also counts water heaters on fewer than 3 phases (power / len(phases) per own line), alongside phase-limited EV chargers. It activates when any phase-limited EV charger OR phase-limited water heater exists. House base load stays net/3.
- UI: phase picker moves to the water heater device settings (VVB tab); the Load Balancing tab shows the heater's phases read-only with a link to the VVB tab.
- `config.default.yaml` comments and user docs updated. Backlog entry updated.

## Capabilities

### New Capabilities
- `water-heater-phase-planning`: per-device water heater phases, shared by planner and balancer, and the planner's per-phase limit including water heaters.

### Modified Capabilities
- `config-migration`: new migration of water heater `loads[].phases` to `water_heaters[].phases`.

## Impact

- Code: `planner/solver/{types,adapter,kepler}.py`, `executor/config.py` (+ balancer wiring in `executor/engine.py`), `backend/config_migration.py`, `backend/api/routers/config.py` (validation: remove empty-phases error for water_heater loads, validate `water_heaters[].phases`), `config.default.yaml`.
- Frontend: `frontend/src/pages/settings/components/EntityArrayEditor.tsx` (water heater card), `GiveWayListEditor.tsx` (shed load phases read-only for water heaters), `types.ts`.
- Docs (approved by the user 2026-11-13): `docs/USER_MANUAL.md`, `docs/BACKLOG.md`, not `docs/ARCHITECTURE.md`. `docs/RELEASE_NOTES.md` is NOT touched.
- No new dependencies, no DB schema change.
