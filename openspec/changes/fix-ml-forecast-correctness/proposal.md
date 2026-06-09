## Why

The stabilization review found six confirmed correctness bugs in the ML forecast pipeline (training → inference → evaluation) that survive the `pv-open-meteo-baseline` work. None of them is a wrong physical action, but each silently degrades or misreports the forecasts the planner depends on: a single malformed timestamp can crash nightly training or corrupt recency weighting; a model trained during a weather-API outage can fail at inference; uncertainty bands can invert; the "PV forecast quality" number shown to users is computed on the wrong basis; and two input failures fall back to wrong-but-silent defaults. These are the residual ML hygiene fixes (findings #9, #10, #15, #16, #17, #18) the review grouped into one change.

## What Changes

- **Robust sample-weight alignment (#15):** recency decay weights are aligned to training rows by label, so a dropped/gapped row (from an un-parseable `slot_start`) can no longer crash training with `IndexError` or silently attach weights to the wrong rows.
- **Train/inference feature symmetry (#16):** training always materialises the same weather feature columns inference expects (NaN-filled when weather is unavailable), so a model trained during an Open-Meteo outage cannot later raise a LightGBM feature-mismatch error or mis-map columns.
- **Monotonic uncertainty bands (#17):** the independently-trained p10/p50/p90 quantiles are repaired to `p10 ≤ p50 ≤ p90` before storage/use, eliminating inverted or zero-width bands feeding the planner's risk logic.
- **Consistent model evaluation (#18):** `ml/evaluate.py` mirrors the live residual pipeline (adds the `physics_forecast_kwh` feature, adds the Open-Meteo baseline back, evaluates all quantiles) so the reported PV-forecast-quality numbers reflect what the model actually does.
- **No load-as-temperature substitution (#9):** the `baseline_7_day_avg` path stops filling a missing `temp_c` column with `load_kwh` values; it uses a neutral default instead.
- **Fail-loud ML inputs (#10):** failed `config.yaml` reads and failed Home-Assistant context-feature fetches log a warning instead of silently returning empty defaults, so degraded forecasts are visible.
- **Open-Meteo gap-fill, no home-grown fallback (OQ5):** when Open-Meteo is missing a single slot within an otherwise-successful fetch, the baseline interpolates from the neighbouring valid slots (falling back to 0 only when no valid neighbour exists) instead of the retired home-grown physics, which over-produces ~2.5× and is bounded only by the physical ceiling.

Out of scope (recorded, not done here): finding #11 (`print()` vs logger), which belongs to `harden-ci-and-tests`. The broader half of OQ5 — retiring the home-grown physics as a *diagnostic feature* — is moot: the feature fed to the model (`physics_forecast_kwh`) already equals the Open-Meteo baseline; only the per-slot NaN-fallback above actually used the physics. A whole-fetch Open-Meteo outage is also out of scope: it is already handled upstream by reusing the last successful stored fetch.

## Capabilities

### New Capabilities
- `ml-forecast-pipeline-integrity`: correctness and fail-loud guarantees across the ML forecast pipeline — feature-set symmetry between training and inference, monotonic quantile outputs, evaluation that mirrors the live pipeline, no substituted-input values, and visible (logged) handling of missing inputs.

### Modified Capabilities
- `recency-weighted-training`: the recency sample-weight requirement gains a robustness guarantee — weights SHALL be aligned to training rows by label (not numpy position), so dropped/gapped rows neither crash training nor misalign weights.

## Impact

- **Code:** `ml/train.py` (sample-weight alignment, training-side weather feature symmetry), `ml/forward.py` (quantile monotonic repair on load + PV; Open-Meteo baseline gap interpolation), `ml/api.py` (quantile repair on read; fail-loud config load), `ml/context_features.py` (fail-loud HA fetches), `ml/evaluate.py` (residual-consistent PV scoring; baseline `temp_c` default), `backend/core/forecasts.py` (daily quantile aggregation reads repaired bands).
- **Behavior:** diagnostics and forecast quality become accurate; no change to the *physical* plan beyond removing inverted/garbage uncertainty inputs. No schema or config changes.
- **Sequencing:** depends on nothing, but should land **after** `recorder-ssot` — that change cleans the `slot_observations` data these models train on, so the model fixes are validated against corrected inputs. No conflict with the paused `price-forecasting-module-3/4/5`.
- **Tests:** new unit tests per finding (malformed-timestamp training row, weather-outage train-then-infer, quantile-crossing repair, evaluator basis, baseline temp_c, silent-fallback logging).
