## Why

Torleif's diagnostics exposed a production path that supplies zero recorded heating progress, an ignored per-heater comfort gap, and chart overlays that can hide planned heating in the current slot. Idle power also counts as heating, making both progress and the display misleading.

## What Changes

- Persist and consume attributable per-heater active heating energy across replans, using the same quota window as the solver and covering both switch and temperature control.
- Add a configurable per-heater idle-power cutoff applied consistently before energy integration and load isolation.
- Make gap comfort use each heater's configured maximum gap, retaining soft penalties and top-up/vacation behavior.
- Preserve legitimate retries and mid-block continuity; prevent already delivered energy from generating another daily-quota request.
- Keep planned heating visible in unfinished slots and overlay only completed, supported measurements. Distinguish unavailable actuals from measured zero.
- **BREAKING**: Validate `water_heating.defer_up_to_hours` within 0–23 hours. Existing values such as 30 must be corrected explicitly; do not silently clamp or reinterpret them.
- Add production-path regression tests and deterministic before/after replays for both control modes.

Solver timeouts, solver selection, performance tuning, and solver-status reporting are deferred to a separate investigation. Daily minimums remain soft minimums, not heating caps; comfort top-ups may still schedule heating after the minimum is met.

## Capabilities

### New Capabilities

- `schedule-measurement-overlays`: Keep schedule plans and supported actual measurements distinct, including unfinished slots and price-only observation rows.

### Modified Capabilities

- `energy-recording`: Retain per-heater energy through storage and corrections; filter idle power consistently while preserving total-load accounting.
- `planner`: Supply measured, attributable heating progress to the production pipeline and retain appropriate retry and mid-block behavior.
- `per-device-water-scheduling`: Align quota accounting windows, validate deferral, honor per-heater gap settings, and expose the idle cutoff.

## Impact

Recorder/history/snapshot/backfill integration, existing observation metadata and store reads/writes, HA initial-state and forecast/pipeline wiring, planner adapter and Kepler water constraints, load disaggregation, schedule history API, and water settings/chart presentation are affected. Use existing metadata storage without a database schema change or new dependencies. Existing unrelated working-tree changes must be preserved. Historical energy cannot always be separated into idle and active consumption; compatibility handling must not invent per-device measurements.
