## Why

With `system.has_water_heater: false` but `water_heaters[]` entries still configured, water heating leaks through several paths. The planner's vacation-mode anti-legionella branch (`planner/pipeline.py` ~1856) rebuilds `kepler_config.water_heaters` from the unfiltered `water_heaters_cfg` and plans water heating. Mid-block detection, heater validation, load disaggregation and the Dashboard also read the unfiltered list. The flag must mean "nothing plans, controls, records, displays or warns about water heating".

## What Changes

- Add one helper, `active_water_heaters(config)`, in `backend/core/water_heating.py`. It returns `[]` when `system.has_water_heater` is false (default true when absent), otherwise the enabled entries (id-less entries are kept, as at HEAD). Every consumer of `water_heaters[]` uses it.
- Planner: derive heaters once from the helper (`water_heaters_cfg`, `enabled_heater_ids`, anti-legionella rebuild, adapter). With the flag off, the vacation branch skips water logic, including reading or writing the anti-legionella record. `config_to_kepler_config` returns no heaters.
- Validation: `validate_water_heating_config` skips the per-heater and `defer_up_to_hours` checks when the flag is off, so stale heater values cannot block planning or saving.
- Recorder (confirmed live bug, Discord user PLL, 2026-10-14: flag false plus enabled `main_tank` with empty `sensor`/`target_entity` recorded water as `unknown` instead of `disabled_zero`, so the grid-only comparison had no data for 10-09 to 10-13): `backend/recorder.py` derives water metadata from the helper so the flag wins. `LoadDisaggregator` does not register water loads when the flag is off.
- `backend/ha_socket.py`: default `True` like every other reader, and use the helper.
- Schedule API: zero the water fields and omit the water heater lists when the flag is off.
- Frontend: gate the CommandBar water controls, the Dashboard boost banner and vacation banner, and the ChartCard water series and legend on the flag. The Heating settings tab stays reachable and shows an informational "disabled" notice.
- Grid-only comparison (part 2): include slots whose only ineligible component is water `unknown` (PLL case and sensor-unavailable case) when load method is `derived_history` and the base-load clamp cannot have triggered; treat null water as 0; add `coverage.water_unmeasured_slots` and `water_unmeasured_hours`; the UI shows a warning note. Applies to all periods and also rescues Kristofer's ~851 existing slots with no rewrite.
- Docs: the BACKLOG note ("harmless leftover the planner ignores") becomes accurate once this lands. Not edited here.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `planner`: the flag applies to all planning paths, including vacation anti-legionella.
- `executor`: the existing flag-gating requirement extends to the load disaggregator, the live socket mapping and validation.
- `sensor-validation`: no water warnings or errors when the flag is off.
- `energy-recording`: recorder records `disabled_zero` when the flag is off, even with stale heater entries.
- `grid-only-comparison`: unmeasured-water slots included with a note.
- `dashboard-ev-display`: water UI is hidden when the flag is off.

## Impact

Files: `backend/core/water_heating.py`, `planner/pipeline.py`, `planner/solver/adapter.py`, `backend/recorder.py`, `backend/grid_only_comparison.py`, `frontend/src/components/CommandDomains.tsx`, `backend/loads/service.py`, `backend/ha_socket.py`, `backend/core/ha_client.py`, `backend/api/routers/{config,schedule}.py`, `frontend/src/{components/CommandBar.tsx,components/ChartCard.tsx,pages/Dashboard.tsx,pages/settings/WaterTab.tsx}`. No schema or dependency changes.
