## 1. Input integrity — fail loud, no substituted values (#9, #10 / D5, D6)

- [x] 1.1 In `ml/evaluate.py:106`, stop filling a missing `temp_c` column with `("load_kwh", "mean")`; fill with NaN (or drop the column from the aggregation when absent)
- [x] 1.2 In `ml/api.py:32–36`, log a `logger.warning` identifying the failure before returning the empty config; narrow the `except` to the expected error types where practical
- [x] 1.3 In `ml/context_features.py:61–66` and `:144–149`, log a `logger.warning` before returning the empty fallback series on a failed HA history fetch
- [x] 1.4 Tests: baseline aggregation never emits load magnitudes in `temp_c`; a forced config-load failure and a forced context-fetch failure each emit a warning

## 2. Recency sample-weight alignment (#15 / D1)

- [x] 2.1 After the dropna/sort that builds the training frame in `ml/train.py` (around `:228`), `reset_index(drop=True)` so label == position before weights are computed/sliced
- [x] 2.2 Make the weight access label-safe at `ml/train.py:418` and `:475` (use `.loc`/reindex semantics or operate on the reset index) so a gapped index cannot misalign or raise `IndexError`
- [x] 2.3 Test: a training set containing one un-parseable `slot_start` row trains without `IndexError` and assigns each surviving row its own recency weight
- [x] 2.4 Test: contiguous (all-valid) data produces weights identical to the previous behavior (no regression)

## 3. Train/inference feature symmetry (#16 / D2)

- [x] 3.1 In `ml/train.py:353–354` and `:405–407`, always materialise all 3 weather columns (`temp_c`, `cloud_cover_pct`, `shortwave_radiation_w_m2`), NaN-filled, so `feature_cols` matches inference regardless of weather availability
- [x] 3.2 Persist the trained feature-name list with the model and validate it in `_load_models`; on mismatch, log a warning and fall back to the Open-Meteo baseline instead of mis-mapping or raising
- [x] 3.3 Test: train with empty `weather_df`, then run inference against that model — no feature-mismatch error, feature lists match
- [x] 3.4 Test: a model whose persisted feature names don't match triggers the warning + baseline fallback

## 4. Monotonic quantile repair (#17 / D3)

- [x] 4.1 At the load quantile write point (`ml/forward.py:300–309`), reorder p10/p50/p90 to non-decreasing before persistence
- [x] 4.2 At the PV quantile write point (`ml/forward.py:415–504`, `:531–536`), apply the same monotonic repair
- [x] 4.3 Apply the repair defensively on read in `ml/api.py:156–161` so historical crossed rows are corrected before the planner / daily aggregation (`backend/core/forecasts.py:325–340`) consume them
- [x] 4.4 Test: crossed inputs are reordered; already-valid bands are returned unchanged; daily aggregation receives monotonic bands

## 5. Evaluation mirrors the live pipeline (#18 / D4)

- [x] 5.1 In `ml/evaluate.py` (`:67–73`, `:135–201`, `:425–430`), build the same feature set as `ml/forward.py` including `physics_forecast_kwh` — reuse the inference feature-building helper rather than a parallel copy
- [x] 5.2 Add the Open-Meteo baseline back to the residual prediction before comparing to actuals, and evaluate all quantiles (not just the p50 alias)
- [x] 5.3 Test: the evaluator's PV predictions reconstruct absolute PV (baseline + residual) and quality is computed on that basis across p10/p50/p90

## 6. Open-Meteo baseline gap-fill (OQ5 / D7)

- [x] 6.1 In `ml/forward.py:385–394`, replace the per-slot NaN fallback to the home-grown physics with linear interpolation between the nearest valid Open-Meteo slots; use 0 when no valid neighbour exists
- [x] 6.2 Keep `physics_kwh` as a display-only output (`forward.py:401`); confirm the model feature `physics_forecast_kwh` already equals the Open-Meteo baseline and needs no change
- [x] 6.3 Test: an isolated NaN slot between valid slots is interpolated; a leading/trailing NaN run falls back to 0, never the home-grown physics

## 7. Verification

- [x] 7.1 Run the full test suite; confirm no regression against the stabilization baseline (1051 passing)
- [x] 7.2 Run `openspec validate fix-ml-forecast-correctness`
- [x] 7.3 Note in release notes that reported "PV forecast quality" numbers will shift to a corrected basis (diagnostic-only, not a regression)
