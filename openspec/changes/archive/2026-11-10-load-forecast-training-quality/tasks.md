## 1. Training data rule

- [x] 1.1 Create `ml/load_clean.py` with constants and `clean_load_observations` (backfill drop, clamp-day detector, stats)
- [x] 1.2 Make `_load_slot_observations` return `quality_flags` and keep slots needed by the detector (load >= 0), keeping the SQL exclude filter; apply `load_kwh > 0.001` after detection
- [x] 1.3 Use the cleaner in `train_models`; log dropped rows/days; store counts in `learning_runs` metrics and the sidecar
- [x] 1.4 Confirm load training uses the historical weather frame (already shipped in `1d1f14a5`)

## 2. Level feature and schema

- [x] 2.1 Add `load_level_7d` computation to `ml/load_clean.py` (complete days, >= 3 days, anchor-hold, NaN)
- [x] 2.2 Add the feature to load features only in `train_models` and `ml/forward.py`
- [x] 2.3 Add `LOAD_SCHEMA_VERSION=2` to sidecars; update `_EXPECTED_LOAD_FEATURES` and `_validate_features` (load only; PV unchanged)
- [x] 2.4 Find the scheduler retrain hook and trigger training on load-schema rejection, at most once per hour

## 3. Blend

- [x] 3.1 Add `slot_means_7d` (strictly before `now`, clean days, >= 3 days else NaN)
- [x] 3.2 Apply `LOAD_BLEND_*` constants in `ml/forward.py` after load inference, shift p10/p90 by the same delta, clamp, keep repair ordering
- [x] 3.3 Leave the baseline and disabled paths unchanged; check S-Index probabilistic inputs (`planner/strategy/s_index.py`, `backend/core/forecasts.py`) are unaffected in spread

## 4. Remove the dead setting

- [x] 4.1 Add `_remove_dead_load_safety_margin` migration in `backend/config_migration.py` and call it pre-merge
- [x] 4.2 Remove both keys from `config.default.yaml`, `samples/config.sample.json`, `frontend/src/pages/settings/types.ts`, `search/guides.ts`, `frontend/src/config-help.json`
- [x] 4.3 Re-grep source and tests for `load_safety_margin` (exclude debugging/, bundles, archive)

## 5. Tests (fake URLs only, no real secrets or webhooks)

- [x] 5.1 Clamp detector: reporter-like fake day flagged, normal day kept, short day and `recording` day kept, backfill dropped
- [x] 5.2 `load_level_7d` and `slot_means_7d`: no leakage, missing-day fallback, DST day
- [x] 5.3 Blend and bands: 0.4/0.6 arithmetic, fallback to p50, p10 <= p50 <= p90 after shift and clamp
- [x] 5.4 Schema mismatch: old load model rejected, retrain triggered once, PV still loads
- [x] 5.5 Load training with mocked historical weather (full, empty, partial)
- [x] 5.6 Migration removes both dead keys, idempotent, merge does not re-add
- [x] 5.7 Run `./scripts/lint.sh` and ml/config tests with `UV_NO_SYNC=1`; frontend typecheck

## 6. Operations (manual, not code)

- [x] 6.1 After release, run `scripts/flag_january_bad_slots.py` (dry run, then `--apply`) on the maintainer's production DB. Requires the user's explicit approval before running — Done 2026-11-10 with user approval (before release): 104 rows flagged, 2026-01-16..20 only. Load values for 2026-01-08..20 look plausible; there the grid/PV/battery data is broken, not load.
- [ ] 6.2 Re-check load forecast accuracy after a few weeks of live data (day bias, evening, 3 h blocks) on the reporting sites
