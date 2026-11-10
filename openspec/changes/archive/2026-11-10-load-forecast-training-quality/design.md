## Context

Verified code facts:

- `ml/train.py:153-172`: four query branches, filter only load/caps/exclude. `train_models` builds one `feature_cols` list (~`:257-279`) shared by load and PV (PV appends `physics_forecast_kwh`).
- Slot columns available: `import_kwh`, `pv_kwh`, `batt_discharge_kwh` (`backend/learning/models.py:18-25`), `quality_flags` JSON with `source` and `recording` (`backend/observation_provenance.py`).
- `ml/forward.py:219-232` expected features; `_load_models` (`:235`) rejects sidecar mismatch and falls back to baseline. Load inference at `:440-450` (clamp 0.01..16 kWh); band repair `sorted([p10,p50,p90])` and the stored `load_forecast_kwh` / `load_p10` / `load_p90` at `~:602-655`.
- S-Index probabilistic (`planner/strategy/s_index.py:160-290`) uses `load_p90 - load_p50` summed per day (slots from the DB, or extended daily aggregates built in `backend/core/forecasts.py:455-505` from the same stored columns) and `target_load = p50 + sigma x uncertainty`. A common shift of p10/p50/p90 therefore leaves the spread, and so the margin factor, unchanged.
- Weather: `get_historical_weather_series` already used in training since `1d1f14a5` (unreleased); `ml/weather.py:424-430` is live inference.
- `load_safety_margin_percent` has no Python reader. Occurrences: `config.default.yaml:255,299`, `samples/config.sample.json`, `frontend/src/pages/settings/types.ts:624,708`, `search/guides.ts:361`, `frontend/src/config-help.json:63` (plus debugging/ captures, `config.yaml`, built bundles, archived openspec; none are source). No test or docs reference. Migrations follow `_migrate_*` pre-merge helpers in `backend/config_migration.py` (e.g. `_migrate_target_margin` at `:704`, called around `:1391`).

## Goals / Non-Goals

**Goals:** load models never learn from clamp-faked or backfill data; recent level input; robust post-model blend; clean model invalidation with auto retrain; remove the dead setting.
**Non-Goals:** PV changes, new weather fetch, L2 models, per-site model selection, DB changes, `docs/`.

## Decisions

1. **Training data rule** in new `ml/load_clean.py`: `clean_load_observations(df) -> (clean_df, stats)`. `_load_slot_observations` also selects `quality_flags` (keeps SQL `exclude`). Rules: (a) drop rows with `source == backfill` and no `recording`; (b) per local day with no `recording` rows and >= 80 slots, compute share of slots with `load_kwh <= 0.02` and any of `import_kwh`, `pv_kwh`, `batt_discharge_kwh` > 0.1; drop the day if share > 0.3. Constants `CLAMP_LOAD_KWH=0.02`, `CLAMP_FLOW_KWH=0.1`, `CLAMP_SHARE=0.3`, `CLAMP_MIN_SLOTS=80`. Local day uses the engine timezone (DST days have 92/100 slots, both >= 80). Note the existing SQL `load_kwh > 0.001` filter would remove clamp slots before detection, so the detector must run on rows loaded without that predicate; implementation loads `load_kwh >= 0`, runs the detector, then applies `> 0.001` afterwards (to verify against the real query when implementing). Validation (backtests): 74/76 reporter fake days, 2 true fake on Kristofer, 0 on maintainer (max 0.281) and PLL (max 0.167).
2. **Level feature** (`load_level_7d`) as specified; computed from the cleaned frame by one function used by train and inference; load features only (`load_feature_cols`), PV `feature_cols` untouched.
3. **Blend** in `ml/forward.py` after load inference and before storage. `slot_mean_7d` is built by `slot_means_7d(clean_obs, slot_starts, now)`: for each forecast slot (local date D, time t) average actual `load_kwh` at t over D-1..D-7 where observations exist, are < `now`, and survive the cleaning rule; require >= 3 else NaN. Inputs: last 8 days of observations, loaded through the same cleaning function (the clamp detector on partial history uses only complete days; partial days are kept as the rule requires >= 80 slots). Final p50 = `0.4 p50 + 0.6 mean` where mean is finite. Constants `LOAD_BLEND_MODEL_WEIGHT=0.4`, `LOAD_BLEND_SLOT_WEIGHT=0.6` in code, not config. Bands: `delta = blended - p50`; `p10 += delta`, `p90 += delta`; clamp to [0.01, 16]; existing repair sort keeps order. S-Index spread stays the model's spread, so probabilistic S-Index behaves as before at a shifted level; the legacy dynamic mode uses p50 only. The model p50 also remains stored? No new column; `base_load_forecast_kwh` receives the blended value as it does today for p50 (consumers treat it as the base forecast).
4. **Schema bump + auto retrain.** `LOAD_SCHEMA_VERSION=2` in sidecar with tier-free stats (dropped counts). `_load_models` records a module-level "load model rejected for schema" flag; the scheduler retrain hook (to locate in `backend`, task 3.4) starts training when set, rate-limited to once per hour. Version 1 / missing = mismatch for load only.
5. **Dead key removal** via `_remove_dead_load_safety_margin` in `backend/config_migration.py`, called with the other pre-merge migrations so the merge cannot re-add; remove from defaults, sample JSON, UI types (both entries), search guide, config-help.json.
6. **Weather**: regression test only.
7. **Reporting**: counts in `learning_runs` metrics and sidecar.

## Rejected alternatives (recorded with reasons)

- **Balance-residual filter (residual > 0.5) as fake-data detector:** false positives on PLL and Kristofer. Rejected.
- **Provenance-only tier (trusted `recording` rows, fallback below a threshold):** earlier design; discards long good legacy history and is neutral where few recording rows exist. Replaced by the clamp rule.
- **50/50 blend:** slightly worse than 40/60 on every site.
- **Average (L2) model; L2 + recent-slot feature; Huber/fair/clipped/regularised mean models:** all swing +14 to +36 % evening in quiet months on the same months; median stays.
- **Recent-slot feature inside the p50 model:** no gain.
- **Bigger/regularised LightGBM:** no gain.
- **Global or per-hour bias-correction factors:** overshot +5-7 %.
- **Shorter half-life (14 d / 7 d / none):** no effect; keep 30 d.
- **Per-site model selection:** backlog.
- **Extending `flag_january_bad_slots.py` or date windows:** per-user; the clamp rule does not catch the January corruption, so a one-off manual run is a task instead.

## Risks / Trade-offs

- Blend adds recent behavior directly: sudden one-off high-load days raise the next week's same slot by 0.6 x deviation / 7-day mean; bounded by averaging and by the weight. Re-check accuracy after a few weeks of live data.
- Fallback to model p50 for slots with < 3 days (fresh installs).
- Clamp rule misses fake days with a lower clamp share; accepted.
- Upgrade: until the automatic retrain finishes, load forecasts use the baseline path.
- Removing the config key is breaking for anyone scripting it; no code reads it, so no behavior change.

## Migration Plan

No DB migration. Config migration deletes two keys. First run after upgrade rejects old load models and triggers retrain. Rollback: revert code; old models are rejected again by v1 validation only if names differ, so retrain after rollback.

## Open Questions

1. Retrain cadence guard of once per hour: recommend keep.
2. Should the blend also be applied to the stored p10/p90 shift when delta is positive (raising the band)? Recommended yes (keeps S-Index spread), as designed.
3. Expose blend weights later as config? Recommend no (code constants, per instruction).
4. Verify the SQL ordering issue in decision 1 against the real query; recommend loading `load_kwh >= 0` for detection.
