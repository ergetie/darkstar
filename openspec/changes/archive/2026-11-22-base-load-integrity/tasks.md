# Tasks

All tests are automated (pytest, `UV_NO_SYNC=1 uv run python -m pytest ...`). Run `./scripts/lint.sh` at the end.

## 1. Shared helpers and predicate

- [x] 1.1 Add `base_load_unreliable(flags)`, `base_load_demand_affected(flags)`, reason constants and `build_base_load_flag(...)` to `backend/measurement_provenance.py`. Verify: unit tests in `tests/test_base_load_flag.py` for reliable, each reason, demand class, malformed input.
- [x] 1.2 Extend `has_unmeasured_device` (`ml/load_clean.py`) and `UNMEASURED_DEVICE_SQL` (`backend/learning/models.py`) with the flag, checked before the `recording` parse. Verify: a parametrised test asserts Python and SQL agree on rows with and without `recording`, NULL, malformed JSON and each reason.
- [x] 1.3 Make `clean_load_observations` ignore flagged rows in the clamp-day statistic and count them in `dropped_unmeasured_device_rows`. Verify: test in the existing load-clean test module.

## 2. Recording

- [x] 2.1 Add the named constant `NOISE_FLOOR_KW = 0.010` to `backend/core/water_heating.py` and apply `max(cutoff, floor)` in `normalize_active_power_kw`. Verify: a test pins the constant value and tests cover 1 W, 9 W, 10 W, 100 W with cutoff 0 and 0.10, W/kW/MW units, and equal results on history, snapshot and backfill paths.
- [x] 2.2 Change `isolate_base_load` to return `BaseLoadIsolation(kwh, clamped)`, update recorder and backfill callers. Verify: tests for exact zero (not clamped), negative (clamped, 0.0, warning logged), no deferrable load.
- [x] 2.3 Expose per-sensor coverage share in `SlotEnergy` using `integrate_power_points_covered` for EV, water and total load, with the named constant `MIN_COVERAGE_SHARE = 0.95`. Verify: a test pins the constant and tests cover device and `load_power` with 10 of 15 minutes, 100 percent, 95 percent boundary, gap marker in the middle.
- [x] 2.4 Add inactive-device sensors to `build_slot_sources`, include them in the single batched history request, compute their active energy. Verify: tests that `has_water_heater: false`, `enabled: false` and `has_ev_charger: false` each fetch the sensor, that no snapshot read is added, and that unconfigured sensors add nothing.
- [x] 2.5 Recorder: write `quality_flags.base_load` (clamp, device and load partial coverage, inactive device), set `load` method `unknown` on clamp, keep device methods unchanged, log the once-per-sensor warning. Verify: `tests/backend/test_base_load_recording.py` (including `load_partial_coverage` setting `load` to `unknown`) covering every scenario in the spec including the unavailable-sensor case (no second flag), disabled idle (no flag) and the unchanged partial-boundary water method.
- [x] 2.6 Backfill: same flags through the shared helper. Verify: test that live and backfill produce equal `base_load` for equal inputs, and that backfill never clears a recorder-owned flag.
- [x] 2.7 `store_slot_observations`: preserve and replace `base_load` in the flag merge (recorder replaces, backfill keeps recorder's). Verify: store test for new row, existing row, and recorder rewrite of a previously flagged slot (flag removed when the new write is reliable).
- [x] 2.8 Guard test that no recorder code path reads a cumulative energy counter for load (assert the sources only use `load_power` history). Verify: test over `build_slot_sources`/recorder entity list.

## 3. Consumers

- [x] 3.1 `ml/forward.py` `determine_graduation_level`: exclude flagged slots. Verify: test with flagged days not counted.
- [x] 3.2 `backend/api/routers/forecast.py` (two actual-load readers) and `backend/api/routers/schedule.py` `actual_load_kwh`: null for flagged slots. Verify: API tests returning null for a flagged slot and the value for a reliable one.
- [x] 3.3 `backend/battery_benchmark.py`, `backend/grid_only_comparison.py`, `backend/observation_provenance.py` `calibration_eligible`: exclude `base_load_demand_affected` rows, keep partial-coverage rows. Verify: tests per consumer for clamp (excluded) and `device_partial_coverage` (kept).
- [x] 3.4 Confirm remaining consumers through the shared clause with one test each: `_base_load_avg_daily_kwh`, forecast-vs-actual and load MAE in `store.py`, monitor energy balance, `ml/evaluate.py` MAE. Verify: each test inserts a flagged and a reliable row and sees only the reliable one.
- [x] 3.5 Load training end to end: a fixture DB with flagged rows (recorder and legacy without `recording`) trains without them and reports the drop count in the sidecar and `learning_runs`. Verify: test in the existing training test module.

## 4. Historical migration

- [x] 4.1 Implement `flag_historical_base_load` in `backend/learning/base_load_migration.py` (rules (a) and (b), union-merge, batches, state key, one transaction). Verify: `tests/test_base_load_migration.py` with fixtures for a row without `recording` (clamp plus following slot), a row with `recording` untouched by (a), rows from an installation with arbitrary dates (no date logic), the 10-03..10-07-style row without `recording`, `disabled_zero` with and without configured sensor, NULL flags, malformed flags, existing keys preserved, mixed UTC offsets, NULL flags, and a check that a log line with per-rule counts is emitted.
- [x] 4.2 Idempotency: run twice and compare the DB dump byte for byte; run after the state key is set and assert no work. Verify: test.
- [x] 4.3 Call it once from the startup lifespan after DB migrations, fail-open (logged, retried next start, never blocks startup). Verify: test that a raising migration does not block startup and that the key is unset after failure.
- [x] 4.4 Test that flagged migrated rows are excluded by the training clause and by the demand consumers (task 3.3), including rows without `recording`.

## 5. Spec and wrap-up

- [x] 5.1 Run the full suite and `./scripts/lint.sh`; fix findings. Verify: both pass.
- [x] 5.2 Validate the change with `openspec validate base-load-integrity --strict`. Verify: exits 0.

## Workflow follow-up

- Follow-up only: a docs note about the 10 W floor next to `idle_power_threshold_kw`. `docs/` is not edited by this change.
- Release notes are not touched unless the user instructs it.
- Commit only on request; do not push.
