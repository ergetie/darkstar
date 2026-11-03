## 1. Unit learning

- [x] 1.1 In `parse_power_states` (`backend/core/ha_client.py`) cache `unit_of_measurement` from any state with attributes before skipping unavailable/unknown/non-numeric states
- [x] 1.2 Add optional keyword `entity_id` to `parse_power_states`; when no unit is known for the series, assume kW and log a WARNING naming the entity at most once per entity per process
- [x] 1.3 In `get_power_history_batch`, for each non-empty series with no unit on any state, read the current unit via `get_ha_entity_state` (concurrently for several entities) and write it into a copy of the first state's `attributes`; a failed lookup leaves the series unchanged

## 2. Request semantics

- [x] 2.1 In `get_power_history_batch` send `significant_changes_only` as "0" and `minimal_response` as an explicit string; comment the HA semantics (presence enables minimal response; only "0" disables significant-only)

## 3. Callers

- [x] 3.1 Pass `entity_id=` to `parse_power_states` in `get_load_profile_from_ha`, `get_energy_from_power_history`, `backend/recorder.py`, `backend/learning/backfill.py`, `backend/core/water_progress.py`; no other caller changes
- [x] 3.2 Confirm by grep that no caller bypasses `get_power_history_batch` for power history

## 4. Tests (fixed non-DST dates, 96 slots; existing files `tests/test_inputs_ha_client.py`, `tests/backend/test_ha_client_power_integration.py`)

- [x] 4.1 Series starting `unavailable`/`unknown` (with unit) then unitless W states parses as W
- [x] 4.2 Series with no unit anywhere gets the current-state unit filled in by `get_power_history_batch`; no extra request when the series already has a unit; failed lookup leaves series unchanged
- [x] 4.3 No unit anywhere: kW assumed, warning logged once per entity
- [x] 4.4 Normal series unchanged; request params assertion ("0", no boolean False)
- [x] 4.5 Load profile with a day chunk starting `unavailable` stays below the plausibility bound and matches the expected kWh
- [x] 4.6 Recorder slot energy for a slot starting `unavailable` on a W sensor is correct

## 5. Verify

- [x] 5.1 Run `./scripts/lint.sh` and the full affected test files
