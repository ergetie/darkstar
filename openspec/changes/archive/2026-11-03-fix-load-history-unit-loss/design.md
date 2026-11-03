## Context

HA history API: `minimal_response` is on whenever the key is present; `significant_changes_only` is on unless equal to "0". Sending Python `False` ("false") therefore enables both. With minimal responses only the first state of a series carries `attributes`. `parse_power_states` only learned the unit from numeric states, so a leading `unavailable`/`unknown` lost it. The 7-day load profile makes seven 1-day requests, so every chunk is exposed.

## Goals / Non-Goals

**Goals:** never mis-scale a W sensor in ANY caller (load profile, recorder slot energy, backfill, water progress, energy-from-history); one shared fix path, no per-caller wiring; no payload blow-up.
**Non-Goals:** changing chunking, the 500 kWh/day bound, or other callers' logic.

## Decisions

1. **Learn unit before skipping the value.** In `parse_power_states`, read `attributes.unit_of_measurement` and update the cached unit before the unavailable/unknown/non-numeric `continue`. Pure and sync; no signature break.
2. **Fallback to the current unit, resolved once in `get_power_history_batch`.** After fetching, for every requested entity whose non-empty series carries no `unit_of_measurement` on any state, `get_power_history_batch` reads the entity's current state via `get_ha_entity_state` and writes that unit into the first state's `attributes` (copying the dict, never mutating shared objects). Contract: every non-empty series returned carries its unit on its first state whenever HA knows it. This covers every caller (recorder, backfill incl. its CPU-bound sync integration, water progress's own unit loop, load profile, energy-from-history) with no per-caller wiring and no signature changes. The extra request happens only for unitless series (rare: e.g. a chunk containing only a restored `unknown` without attributes). Lookups run concurrently for multiple entities; a failed lookup leaves the series unchanged (falls to decision 3). Per-call only, no global cache (a sensor's unit may be reconfigured). A unit change across history is not handled (out of scope).
3. **Unit unknown everywhere: keep kW default and log a warning, once per entity.** `parse_power_states` gains an optional keyword `entity_id` used only for the warning; callers that know the entity pass it. To avoid log spam from the 15-minute recorder, the warning is emitted at most once per entity per process (module-level set), at WARNING. Raising or dropping the series would turn a harmless misconfiguration (true kW sensors with no attributes, test fixtures) into lost data; the 500 kWh/day bound remains the safety net for W sensors. The warning makes the guess visible.
4. **Request semantics: keep minimal response, send `significant_changes_only` = "0".** Full attributes cost ~16k states/day/sensor times hundreds of bytes (several MB per day-chunk, per sensor), raising the 12 s timeout and memory risk. Decisions 1 and 2 remove the dependence on attributes beyond the first state. Send the flags as explicit strings ("0" and "true") so the code states what HA does.

## Risks / Trade-offs

- Extra `get_ha_entity_state` call in the rare unitless case; failure falls through to the kW warning.
- If HA ever returned attributes inconsistently, decision 2 still covers it.

## Callers covered

All callers go through `get_power_history_batch` + `parse_power_states`: `get_load_profile_from_ha`, `get_energy_from_power_history`, `backend/recorder.py` (15-min slot energy, equally exposed after outages), `backend/learning/backfill.py`, `backend/core/water_progress.py` (its `_history_energy` unit loop already caches from all states but its `valid_by_time` uses `parse_power_states`). No caller signature changes; callers only add `entity_id=` to `parse_power_states` where cheap.
