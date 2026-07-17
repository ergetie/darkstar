# Design: price-forecast-anchoring

## Context

Investigated 2026-07-10 (recorded in project memory `project-real-fixes-investigations`):

- `ml/price_features.py:build_price_features_batch` already supports lag population — it takes an optional `db_session` and calls `_get_price_lags` per slot, which point-queries `slot_observations.export_price_sek_kwh` at slot−1d, slot−7d, and a trailing-24h window, returning NaN when rows are absent.
- `ml/price_forecast.py:generate_price_forecasts` (the production inference path) calls it **without** `db_session` (lines 181-186), so every production forecast row is built with all three lags NaN. LightGBM tolerates NaN via default-branch routing, so this fails silently.
- `ml/price_train.py:_build_training_dataset` → `_add_price_lag_features` (line 180, function at 203+) populates lags for every training row from historical observations, unconditionally. For a `days_ahead=5` row, `price_lag_1d` (actual price the day before the target) was not knowable at issue time — leakage. The training df carries `issue_timestamp` per row (line 174), so knowability is decidable row-by-row.
- The existing spec (`price-forecasting`, "Price forecast feature engineering") already mandates lag features with NaN for missing values; the current inference behavior violates its intent (lags are *always* missing by omission, not by data availability).

## Goals / Non-Goals

**Goals:**
- Inference receives real lag values wherever the observation exists (D+1 near-boundary slots get `lag_1d`/`24h_avg`; all horizons get `lag_7d`).
- Training lag features contain only values knowable at the row's `issue_timestamp`.
- Model retrained on the corrected dataset; midnight-boundary behavior verified on production data.

**Non-Goals:**
- No boundary blending/bias-correction post-processing (only reconsidered if the acceptance check fails, as a separate change).
- No new features (e.g. `price_last_known`) — smallest fix first; feature additions are a separate discussion if needed.
- No changes to model architecture, quantile setup, scheduling, or the persistence/dedup logic.
- No batch-optimization of the per-slot lag queries (scheduled job, ~2k point queries is fine).

## Decisions

### D1: Populate inference lags by passing a session, not by new code paths

`generate_price_forecasts` already knows `db_path` and already imports `create_engine`/`sessionmaker` (used by `_persist_forecasts`). Open one session before the D+1..D+7 loop, pass it to every `build_price_features_batch` call, close it in a `finally`. No changes to `price_features.py`. Alternative rejected: pre-fetching lags in bulk — more code for a non-hot path.

### D2: Knowability at inference is enforced by data availability, deliberately

At inference time, `slot_observations` only contains the past — querying slot−1d for a D+2 slot finds no row and yields NaN naturally. No masking logic is needed (or wanted) at inference; adding one would duplicate the DB's ground truth.

### D3: Training masks by `issue_timestamp` comparison

In `_add_price_lag_features`, for each row keep a lag only if its source timestamp strictly precedes the row's `issue_timestamp`:
- `price_lag_1d`: keep iff `(slot_start − 1 day) < issue_timestamp`
- `price_lag_7d`: keep iff `(slot_start − 7 days) < issue_timestamp`
- `price_lag_24h_avg`: keep iff the window END `(slot_start − 1 day) < issue_timestamp` (whole-window rule, KISS — a partial-window average would use a different data distribution than inference produces)

This makes the training-time feature distribution match what inference can produce per horizon: `days_ahead=1` rows keep lags for slots whose yesterday-hour precedes issue time; higher horizons mostly get NaN `lag_1d`/`24h_avg` but keep `lag_7d` where it precedes issue time. Alternative rejected: masking by `days_ahead` bucket — cruder, wrong at day edges, and ignores the actual issue clock.

### D4: Retrain is part of this change's verification, not a separate step

The fix is inert until the model is retrained on masked data (a model trained on leaked lags, fed real lags, is an improvement but not the verified end state). Verification runs the existing training entry point, regenerates forecasts, and compares the D+1 boundary against recent actuals on production data. Acceptance: the 00:00 boundary step is in line with typical slot-to-slot variation, no systematic level jump attributable to missing anchoring.

## Risks / Trade-offs

- [Sparser training features] Masking raises NaN rates for `lag_1d`/`24h_avg` on D+2..D+7 rows; if training data is thin, model quality could dip on far horizons → those horizons currently get NaN at inference anyway, so honesty ≥ status quo; d1_mae/KPI monitoring (existing `price-forecast-accuracy-kpi`) tracks regression.
- [Timezone/string matching] `_get_price_lags` matches `slot_start` by exact ISO string; inference slots are tz-aware Europe/Stockholm, same as observations → verified pattern already used in training joins; test with a real observation row to be sure (task).
- [Session lifetime] A single session across a long generation loop → read-only point queries, SQLite; wrap in try/finally, no transaction accumulation.
- [Expectations] Anchoring improves the boundary but D+2..D+7 remain calendar+weather+`lag_7d` models — the fix targets the boundary discontinuity, not overall MAE.

## Migration Plan

Code deploy → next scheduled training run picks up masked features (or trigger a manual retrain during verification) → next forecast generation writes anchored forecasts. Rollback: revert commit; old model files remain compatible (feature list unchanged — same columns, different values/NaN pattern).

## Open Questions

_None — approach decided with the user 2026-07-11/12 (root-cause fix only, blend excluded unless acceptance check fails)._
