## Context

`record_observation_from_current_state` (`backend/recorder.py:218`) today computes:
- EV and water: `get_energy_from_power_history` per entity, sequentially, over `[slot_start, slot_end]`.
- PV, load, grid, battery: `calculate_energy_from_cumulative` (`recorder.py:406`), which reads the latest counter value and calls `RecorderStateStore.get_delta` (`recorder.py:93`), scaling the delta by `900 / (sensor_ts − previous_sensor_ts)`. Fallback is the power snapshot × 0.25 h.

On production the counters update about every 10 minutes (00:00:00, 00:10:04, 00:20:14, 00:29:58 local on 2026-10-01) in 0.1 kWh steps, so the stored values describe a shifted window. Reproduced for 00:15: stored import 1.51 = (10947.2 − 10945.2) × 900/1194, versus 1.91 integrated.

Measured on production (read-only, 2026-09-24 → 10-02): integrating `sensor.total_pv_power`, `sensor.inverter_load_power`, `sensor.inverter_grid_power` (split by sign) and `sensor.inverter_battery_power` (split by sign) over each local day matches the counter deltas within 0.1% in total and within 0.11 kWh on every day. Samples: load/grid ~16k/day (max gap ≤ 2 min), battery ~12–15k/day (max gap 15.5 min once), PV ~12k/day (long gaps only overnight at 0 W).

Counters are also read by backfill (`backend/learning/backfill.py`, `engine.etl_cumulative_to_slots`), the forecasting load profile (`ha_client.get_load_profile_from_ha`), health (`health.py:646-767, 985-1020`), onboarding (`entity_roles.py`, `entity_matcher.py`, `setup.py`, frontend wizard), settings, `config-help.json`, two manual scripts (`bin/backfill_ha.py`, `ml/data_activator.py`) and dead add-on option mappings (`darkstar*/run.sh:259-263`).

## Goals / Non-Goals

**Goals:**
- One method for all slot energy: step integration of power history over the exact completed slot.
- No counter configuration, code path or state anywhere.
- Existing configs migrate silently; no user action.
- Power sensors stay required exactly as readiness already enforces.

**Non-Goals:**
- Correcting historical rows.
- Changing the 10-day backfill cap, the slot-alignment rules, `validate_energy_values` or the store's authoritative/backfill write rules.
- The hard-coded `Europe/Stockholm` timezone in the load profile (separate issue, unchanged).
- Database schema changes.

## Decisions

**1. Power history is the only primary method, for every metric including battery.** The production comparison shows no drift against the counters, and only a high-rate signal can place energy in the right slot. Interpolating counters at slot boundaries was rejected: it cannot resolve 10-minute plateaus and is quantised to 0.1 kWh.

**2. A shared integrator returns `(positive_kwh, negative_kwh)`.** The existing step-integration core in `get_energy_from_power_history` (zero-order hold, pre-window state, excluded states, first-state unit propagation, W/kW/MW) is extracted into one helper used by the recorder, backfill and load profile. `get_energy_from_power_history` becomes a thin wrapper returning the signed sum, so EV and water results are unchanged. Splitting happens per sample interval, so simultaneous import/export swings inside a slot are not netted away.

**3. Sign conventions are applied before splitting.** Net grid: after `grid_power_inverted`, positive = import, negative = export. Battery: after `battery_power_inverted`, positive = discharge, negative = charge (the documented convention in `config.default.yaml`). Dual grid: import and export sensors are integrated separately and negative samples are clipped to 0 (they are non-negative by role, `readiness.py:90`). PV and load: negative samples clipped to 0 for the same reason. Inversion uses the same flags and semantics as the executor's snapshot path (`recorder.py:392-402`), not new logic.

**4. One batched history request per slot.** All configured power entities for the slot (PV, load, grid net or import/export, battery, enabled EV chargers, enabled water heaters) are fetched with a single `/api/history/period` request using a comma-separated `filter_entity_id`, with the existing 12 s timeout. The response is split per entity and integrated. A failed request yields no history for every entity, and each metric falls back to its snapshot. This replaces up to N sequential requests and keeps HA load at one request per slot. HA support for comma-separated `filter_entity_id` is verified against the production HA in task 1 before building on it.

**5. Fallback per metric is the power snapshot × 0.25 h.** Identical to EV and water. No counter fallback exists anymore. The snapshot batch (`gather_sensor_reads`) is kept because it is the fallback source and is used by the disaggregator.

**6. Load isolation.** The integrated total load has EV and water subtracted and is clamped at 0, as the spec already requires. When load falls back to the snapshot, the existing disaggregator base-load behaviour (snapshot already isolated, no second subtraction) is kept. The condition in `recorder.py:532-540` is rewritten from "used cumulative load" to "load came from history".

**7. Backfill integrates power history too.** Gap detection (last observation → now, capped at 10 days) is unchanged. History for all power entities is fetched in batched requests covering one local day each, integrated per 15-minute slot with the shared integrator, load-isolated the same way as the live path, and written with `authoritative=False`. SoC handling stays. `etl_cumulative_to_slots`, `_canonical_sensor_name` aliasing and `learning.sensor_map` are removed because they only exist to map counter series; entities come directly from `input_sensors`, `ev_chargers[]` and `water_heaters[]`. Spike filtering uses `get_max_energy_per_slot` via the existing `validate_energy_values`.

**8. Load profile from `load_power` history.** `get_load_profile_from_ha` integrates 7 days of `load_power` history with the shared integrator into the existing 96-slot local distribution (`_distribute_interval_energy`) and divides by 7. It stays total load, as today. The 500 kWh/day backstop and the per-slot clamp stay. The counter-delta skip guard and `max_meter_delta_kwh` go. The 7-day request is split into daily requests to bound response size.

**9. Synthetic baseline becomes the "no usable history" fallback.** `synthetic_daily_load_kwh` is used when `load_power` is configured but its history is empty, all zero, or discarded by the backstop, replacing the flat 0.5 kWh demo profile in that case. With no value set, the demo profile and degraded status remain. Onboarding shows it as an optional field without the counter-vs-estimate toggle and no longer requires it for step completion.

**10. Config removal via migration.** Add the six `input_sensors.total_*` keys, `recorder.max_meter_delta_kwh` and `learning.sensor_map` to `DEPRECATED_NESTED_KEYS` (`config_migration.py:93`), so `remove_deprecated_keys` drops them before and after `template_aware_merge` (which would otherwise preserve them). `_migrate_synthetic_load` already runs earlier (`config_migration.py:1282`), so a legacy numeric `total_load_consumption` is moved to `synthetic_daily_load_kwh` before the key is removed. The `consumption_entity_id` read in `ha_client.py:741` is deleted.

**11. Health checks.** Remove the six counter entries from `sensor_requirements` (`health.py:662-668`) and the "missing cumulative sensors" warning (742-767). Without that, the migration would trigger "Missing required sensor: total_*" as CRITICAL for every learning-enabled install. The load-forecast degraded messages (994-1017) name `load_power` instead of `total_load_consumption`.

**12. Recorder state file.** `RecorderStateStore` is removed. `RecorderService` deletes `data/recorder_state.json` once at startup if present (logged at info), so no orphaned state remains. The "Single Live Recorder Instance" requirement stays, with its rationale updated: concurrent recorders would still double-write authoritative rows, but the meter-state race no longer exists.

**13. Manual scripts are deleted, not ported.** `bin/backfill_ha.py` depends on hourly long-term statistics of the counters and `ml/data_activator.py` on raw counter history. The automatic backfill covers the 10 days where 15-minute data exists; beyond that no source can fill slots.

## Risks / Trade-offs

- [Another user's power sensor updates slowly] → Step integration still holds the last value, the same contract EV and water already rely on. A sensor reporting every few minutes is still at least as accurate as a 10-minute counter. Not detectable from config; accepted.
- [Wrong sign configuration produces swapped import/export or charge/discharge] → Same flags the executor already depends on to control the inverter; a wrong flag is already visible there. Tests cover both flags.
- [Batched multi-entity request fails] → All metrics fall back to snapshots for that slot, logged once. Same result as today's per-entity failure, but correlated. Accepted for the reduced HA load.
- [Backfill of 10 days requests a lot of history] → Batched per day: at most 10 requests, each ~16k samples per entity on production. Run once at startup, off the event loop where it is today.
- [Removing config keys breaks a user's custom setup] → Migration is silent and idempotent; nothing reads the keys afterwards. Covered by migration tests.
- [ML sees different slot values] → Daily totals are equal within 0.1%; only within-day placement improves.
- [Rows before the change keep lagged values] → No migration of data; documented.

## Migration Plan

1. Deploy normally. Startup config migration removes the obsolete keys; `RecorderService` removes `data/recorder_state.json`.
2. The first slot after start is recorded from power history; no warm-up slot is needed, since there is no counter baseline.
3. Rollback: revert the change. The reverted recorder re-creates its state file and starts with one snapshot-fallback slot per counter (existing cold-start behaviour). Removed config keys must then be re-entered by the user; this is the one non-free part of a rollback and is accepted.

## Open Questions

None.
