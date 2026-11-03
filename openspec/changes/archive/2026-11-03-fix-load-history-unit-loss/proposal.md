## Why

On a W-reporting load sensor the planner discarded the 7-day load profile ("2726.9 kWh/day exceeds the 500 kWh/day plausibility bound") and used the 0.5 kWh flat demo profile for days. Root cause: the profile is fetched as seven 1-day history requests. HA's history API treats `minimal_response` as ON by mere presence of the key (and `significant_changes_only` as ON unless "0"), so only the first state of each series carries `attributes`. `parse_power_states` reads the unit only from numeric states, so when a chunk's first state is `unavailable`/`unknown` (e.g. after an outage) the unit is never learned, W is treated as kW and that day is inflated 1000x. The error persists until the outage leaves the 7-day window.

## What Changes

- `parse_power_states` learns the unit from any state carrying attributes, including non-numeric ones, before skipping the value.
- `get_power_history_batch` guarantees each returned series carries its unit: when no state has one, it fills in the entity's current `unit_of_measurement`. Every caller is covered without per-caller wiring. If still unknown, kW is assumed and a warning is logged once per entity.
- The history request states its semantics explicitly: `significant_changes_only` is sent as "0" (all changes wanted) and the minimal-response behaviour is kept deliberately (not sent as `False`).
- Tests for the above. No behaviour change for normal series.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `energy-recording`: power-history parsing must never lose or guess the sensor unit.

## Impact

- `backend/core/ha_client.py` (`parse_power_states`, `get_power_history_batch`).
- Shared helpers also used by `backend/recorder.py`, `backend/core/slot_energy.py` paths, `backend/core/water_progress.py`, `backend/learning/backfill.py`, `get_energy_from_power_history`; all covered by the shared fix (the recorder's 15-min slot energy is exposed the same way after outages).
- Tests in `tests/test_inputs_ha_client.py` and `tests/backend/test_ha_client_power_integration.py`. No schema, config or dependency changes.
