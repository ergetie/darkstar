## 1. Pre-check

- [x] 1.1 Read-only against production HA: confirm one `/api/history/period` request with a comma-separated `filter_entity_id` (all slot entities) returns one series per entity, with the unit on the first state of each series. Stop and report if not; design decision 4 depends on it.

## 2. HA client integrator

- [x] 2.1 In `backend/core/ha_client.py`, extract the step-integration core of `get_energy_from_power_history` into a shared helper that takes parsed states plus `[start, end]` and returns `(positive_kwh, negative_kwh)` or `None`. Keep zero-order hold, pre-window state, excluded states, first-state unit propagation and W/kW/MW exactly as today.
- [x] 2.2 Add a batched fetch that requests several entities in one call (comma-separated `filter_entity_id`, 12 s timeout, shared HTTP client) and returns states per entity; on failure return `None` and log one warning.
- [x] 2.3 Make `get_energy_from_power_history` a thin wrapper returning the signed sum, so EV and water results are unchanged.
- [x] 2.4 Remove `_normalize_energy_to_kwh` and every caller once nothing reads counters.

## 3. Recorder

- [x] 3.1 In `backend/recorder.py`, build the slot's entity list (PV, load, grid net or import/export, battery, enabled EV chargers, enabled water heaters, skipping disabled subsystems) and fetch it with one batched request over `[slot_start, slot_end]`.
- [x] 3.2 Integrate each metric with the shared helper and apply the sign rules: net grid after `grid_power_inverted` (+import/−export), battery after `battery_power_inverted` (+discharge/−charge), negatives contribute 0 for PV, load, dual import/export, EV and water.
- [x] 3.3 Per metric, fall back to the power snapshot × 0.25 h with the same sign rules when integration gives no value. Keep the snapshot batch (`gather_sensor_reads`) and the disaggregator.
- [x] 3.4 Rewrite load isolation (`recorder.py:532-540`): subtract EV and water from integrated total load with the clamp and warning; when load fell back to the snapshot, keep the disaggregator base-load behaviour without a second subtraction.
- [x] 3.5 Record disabled subsystems as `0.0` without history; align the water-heater path with `has_water_heater` (today it is skipped only for the snapshot read).
- [x] 3.6 Delete `RecorderStateStore`, `calculate_energy_from_cumulative`, `get_cumulative_kwh*`, the `state_store` parameter and the `max_meter_delta_kwh` read; update callers in `backend/recorder_service.py` and `backend/api/routers/learning.py`.
- [x] 3.7 In `RecorderService` startup, delete `data/recorder_state.json` if present, with an info log.

## 4. Backfill

- [x] 4.1 In `backend/learning/backfill.py`, derive entities from `input_sensors`, `ev_chargers[]` and `water_heaters[]` (same list builder as the recorder) and fetch history in batched requests of at most one local day each; keep the gap detection and 10-day cap.
- [x] 4.2 Integrate each 15-minute slot with the shared helper and the same sign rules, apply the same load isolation, run `validate_energy_values` with `get_max_energy_per_slot`, keep SoC handling, and write with `authoritative=False`. Include battery charge/discharge.
- [x] 4.3 In `backend/learning/engine.py`, remove `etl_cumulative_to_slots`, `_canonical_sensor_name` aliasing and `sensor_map`; keep or delete `etl_power_to_slots` depending on whether anything still uses it after 4.2.
- [x] 4.4 Delete `bin/backfill_ha.py` and `ml/data_activator.py`; remove the `pyproject.toml` lint entry, the `bin/explode_rows.py:50` comment and the `ml/train.py:346` hint that names `data_activator`.

## 5. Load profile

- [x] 5.1 Rewrite `get_load_profile_from_ha` to integrate 7 days of `input_sensors.load_power` (daily requests) into the existing 96-slot distribution and divide by 7; keep the per-slot clamp and the 500 kWh/day backstop; remove the counter-delta skip guard and the `consumption_entity_id` fallback.
- [x] 5.2 In `get_dummy_load_profile`, use `synthetic_daily_load_kwh` whenever load history is unusable (not configured, no valid samples, or discarded), otherwise the demo profile; distinct `discard_reason` texts for "not configured", "no history" and "discarded"; replace the `total_load_consumption` log hint with `load_power`.

## 6. Configuration and migration

- [x] 6.1 Add the six `input_sensors.total_*` keys, `recorder.max_meter_delta_kwh` and `learning.sensor_map` to `DEPRECATED_NESTED_KEYS` in `backend/config_migration.py`; confirm `_migrate_synthetic_load` still runs before removal.
- [x] 6.2 Remove those keys and their comments from `config.default.yaml`; update the `synthetic_daily_load_kwh` comment to "used when load power history is unusable".
- [x] 6.3 Remove the counter option mapping in `darkstar/run.sh` and `darkstar-dev/run.sh` (lines ~259-263).

## 7. Health

- [x] 7.1 In `backend/health.py`, remove the counter entries from `sensor_requirements`, the "REV F65" comment and the "missing cumulative sensors" warning.
- [x] 7.2 Update the load-forecast degraded messages to name `load_power` per the load-history-sanitization spec.

## 8. Onboarding and settings

- [x] 8.1 Backend: remove the six `total_*` rules from `entity_roles.py` (`ROLE_RULES`, `ROLE_PATHS`, `ENERGY_UNITS` if unused), the cumulative branch of `entity_matcher.py`, and the `cumulative` flag in `api/routers/setup.py`.
- [x] 8.2 Frontend onboarding: remove counter roles from `OnboardingWizard.tsx` suggestions, `steps.tsx` (`ROLE_LABELS`, `CoreSensorsStep` counter fields, cumulative plausibility text, counter-vs-estimate toggle, `commonSensorPaths`), `helpers.ts` labels; make `synthetic_daily_load_kwh` an optional field and drop it from `isComplete`.
- [x] 8.3 Settings: remove the three "Lifetime Energy Totals" sections from `frontend/src/pages/settings/types.ts` and the reference in `settings/search/guides.ts`.
- [x] 8.4 Remove the six counter entries from `frontend/src/config-help.json`; update the `synthetic_daily_load_kwh` help if present.

## 9. Tests

- [x] 9.1 HA client: positive/negative split, sign flip, unit propagation per entity in a batched response, empty and failed batches, unchanged EV/water results.
- [x] 9.2 Recorder: one request per slot; net, inverted net, dual; battery and inverted battery; per-metric snapshot fallback; batch failure; disabled subsystems; load isolation for history and snapshot paths; the 2026-10-01 00:15 case (`import_kwh` ≥ `ev_charging_kwh`, no clamp).
- [x] 9.3 Backfill: gap filled from power history incl. battery; at most one request per local day; 10-day cap; spike filtering; load isolation.
- [x] 9.4 Load profile: constant 1 kW → 24 kWh/day; 500 kWh backstop; synthetic used for no-history and discarded cases; degraded messages.
- [x] 9.5 Migration: removal of all eight keys, survives template merge, numeric load moved first, idempotent. Health: no missing-sensor issue after migration.
- [x] 9.6 Startup removes `recorder_state.json`.
- [x] 9.7 Rewrite or delete counter tests: `tests/backend/test_recorder_deltas.py` (state store, deltas, time scaling, battery cumulative, interpolation classes), `tests/fault_injection/test_sensor_anomalies.py`, `tests/fault_injection/test_restart_staleness.py`, `tests/backend/test_ha_client_load_profile.py`, `tests/backend/test_energy_normalization.py`, `tests/backend/test_onboarding_backend.py`, `tests/test_inputs_ha_client.py`, `tests/health/test_health_issue.py`, `tests/ml/test_backfill.py`, `tests/ml/test_learning_engine.py`, `tests/ml/test_ml_aggregation.py`, `tests/backend/services/test_recorder_service.py`, `OnboardingWizard.test.tsx`.
- [x] 9.8 `rg` for `total_pv_production|total_load_consumption|total_grid_import|total_grid_export|total_battery_charge|total_battery_discharge|max_meter_delta_kwh|sensor_map|consumption_entity_id|recorder_state|etl_cumulative` outside `openspec/changes/archive`, `docs/archive`, `docs/RELEASE_NOTES.md` and the migration's key list returns nothing.

## 10. Specs and docs

- [x] 10.1 Sync the delta specs into `openspec/specs/` on archive; update the `energy-recording` Purpose line (it still says "using cumulative meter sensors").
- [x] 10.2 Update (approved by user 2026-10-03) `docs/ARCHITECTURE.md:1131` and `docs/DEVELOPER.md:160-167` to the power sensors.

## 11. Verification

- [x] 11.1 `UV_NO_SYNC=1 uv run python -m pytest -v`, frontend tests, then `./scripts/lint.sh`; all green.
- [x] 11.2 Read-only replay on production (no DB writes): run the new recorder slot computation and the new backfill computation for every slot of the last 7 days against production HA history. Compare daily totals per metric against the counter deltas (accept within ±1% or ±0.2 kWh per day, the measured drift being ≤ 0.11 kWh) and list slots differing from stored rows by more than 0.3 kWh, confirming they are lag cases (EV start/stop, counter step). Stop and report on any failure.
  - Result (accepted 2026-10-03): 41/42 day-metric pairs within tolerance; the one miss (2026-09-28 battery discharge 23.93 vs 24.20 kWh) is explained by the server being off ~15.5 min that day (battery sensor history gap).
- [x] 11.3 Migration dry run on a copy of the production `config.yaml`: removed keys gone, all other values identical, health shows no new issues.
