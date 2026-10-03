## Why

PV, load, grid and battery energy are recorded from cumulative inverter counters. On production these counters update only about every 10 minutes in 0.1 kWh steps. The recorder reads whatever the counter last said at the slot boundary, so these fields describe a shifted window, while EV and water are integrated from power history over the exact slot. `energy-recording` already requires every field to describe the same window ("Slot Alignment to Completed Window"); the counter path cannot meet it.

Verified on production, 2026-10-01 00:15 (EV charge start): the counter gave `import_kwh = 1.51`, while integrating the inverter grid power over the exact slot gives 1.91 (EV 1.65 + house ~0.24). At 01:30 the stored import is 1.04 against 1.92 integrated. The same lag makes `load_kwh` clamp to 0 ("Negative base load" warnings, 13 in the last week) and made the EV card show phantom solar.

Power history is accurate enough to replace the counters entirely. A read-only comparison on production over 2026-09-24 → 2026-10-02 (9 days) of step-integrated power history against the counters gave totals within 0.1% for every metric (PV −0.1%, load −0.1%, import 0.0%, export 0.0%, battery charge 0.0%, battery discharge −0.1%), and no day differed by more than 0.11 kWh, which is the counters' own 0.1 kWh resolution. Load and grid sensors report every ~5 s, battery every ~6–7 s.

Counters give no benefit beyond HA's history retention either: past the default 10 days only hourly long-term statistics remain, which cannot fill 15-minute slots. Keeping counters anywhere would leave two methods and six extra required sensors for no gain.

## What Changes

- **Recorder**: `pv_kwh`, total load, `import_kwh`, `export_kwh`, `batt_charge_kwh` and `batt_discharge_kwh` are step-integrated from the configured power sensors' HA history over exactly `[slot_start, slot_end]`, the method already used for EV and water. Net grid and battery are split by sign per sample interval after applying `grid_power_inverted` / `battery_power_inverted`. Dual meters integrate the import and export sensors. Fallback per metric is the power snapshot × 0.25 h, as for EV and water.
- **One history request per slot**: all power entities (PV, load, grid, battery, EV, water) are fetched in a single HA history call instead of one sequential call per entity.
- **Backfill** fills gaps (up to the existing 10-day cap) by integrating power history for every metric, including battery, fetched in day-sized batched requests. The counter interpolation path (`etl_cumulative_to_slots`) is removed.
- **Load profile for forecasting** is built from 7 days of `load_power` history instead of the load counter. The 500 kWh/day backstop and the degraded-status messaging stay, now naming `load_power`.
- **BREAKING (config)**: the six counter keys `input_sensors.total_pv_production`, `total_load_consumption`, `total_grid_import`, `total_grid_export`, `total_battery_charge`, `total_battery_discharge` are removed, together with `recorder.max_meter_delta_kwh`, `learning.sensor_map` and the legacy `secrets.home_assistant.consumption_entity_id` fallback. A startup migration removes them from existing configs; no user action needed.
- **Removed code**: `RecorderStateStore` and `data/recorder_state.json` (deleted once at startup), counter energy normalisation, the counter branch of entity matching, the manual long-term-statistics backfill `bin/backfill_ha.py`, the manual counter backfill `ml/data_activator.py`, and the dead counter option mapping in the add-on `run.sh` files.
- **Health, onboarding and settings** stop asking for or checking counters. The power sensors stay required exactly as readiness already enforces them (`backend/core/readiness.py`).
- **Synthetic load baseline** (`synthetic_daily_load_kwh`) is kept as an optional value, used when `load_power` history yields no usable data; the onboarding "total energy sensor vs estimate" toggle is removed.
- No database schema change. Rows recorded before the change keep their values.

Independent of `ev-solar-attribution-pv-bound`; together they remove the under-recorded charge-start imports that still affect EV cost.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `energy-recording`: all slot energy (PV, load, grid, battery, EV, water) is integrated from power history over the exact slot window; counter requirements, recorder state file and counter backfill are removed; backfill integrates power history.
- `load-history-sanitization`: the load profile is built from `load_power` history; the counter-delta guard is removed; degraded messaging names `load_power`.
- `sensor-configuration`: the six counter keys are removed and migrated away; tooltip requirement for counters removed.
- `startup-wizard`: the core sensors step no longer collects counters or a baseline choice; synthetic daily load is an optional value.
- `synthetic-load-baseline`: the synthetic profile is used when `load_power` history is unusable, instead of when no load counter is configured.

## Impact

- **Backend**: `backend/recorder.py`, `backend/recorder_service.py`, `backend/core/ha_client.py`, `backend/learning/backfill.py`, `backend/learning/engine.py`, `backend/health.py`, `backend/core/entity_roles.py`, `backend/core/entity_matcher.py`, `backend/api/routers/setup.py`, `backend/config_migration.py`, `config.default.yaml`.
- **Removed scripts**: `bin/backfill_ha.py`, `ml/data_activator.py` (plus their `pyproject.toml` lint entry and the `bin/explode_rows.py` comment).
- **Frontend**: onboarding (`helpers.ts`, `steps.tsx`, `OnboardingWizard.tsx` + test), settings (`settings/types.ts`, `settings/search/guides.ts`), `config-help.json`.
- **Add-on**: `darkstar/run.sh`, `darkstar-dev/run.sh`.
- **Specs**: `energy-recording`, `load-history-sanitization`, `sensor-configuration`, `startup-wizard`, `synthetic-load-baseline`.
- **Docs** (approved): `docs/ARCHITECTURE.md`, `docs/DEVELOPER.md`.
- **Tests**: recorder, HA client, backfill, learning engine, load profile, energy normalisation, health, onboarding, migration, fault injection, frontend wizard.
- **Data**: slot-level PV, load, grid and battery values become slot-accurate. ML consumes them; daily totals were verified equal to the counters within 0.1%, so no distribution shift is expected. Release verification replays the new code against production history.
