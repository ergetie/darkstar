## Context

Six confirmed bugs in the ML forecast pipeline survive the `pv-open-meteo-baseline` work (stabilization-review findings #9, #10, #15, #16, #17, #18). They span three stages — training (`ml/train.py`), inference (`ml/forward.py`, `ml/api.py`, `ml/context_features.py`), and evaluation (`ml/evaluate.py`) — plus the daily aggregation read in `backend/core/forecasts.py`. None changes a physical action; each silently degrades or misreports the forecasts the planner consumes. The fixes are local and independent of each other, but cluster in the same files, so they ship as one change. Constraint: no schema or config changes; models continue to retrain nightly.

## Goals / Non-Goals

**Goals:**
- Make ML training robust to a single malformed `slot_start` row (no crash, no weight misalignment).
- Guarantee a model can always be served: training and inference agree on the feature set.
- Guarantee `p10 ≤ p50 ≤ p90` everywhere a band is stored, read, or aggregated.
- Make the reported PV-forecast-quality number reflect the model the system actually runs.
- Make missing-input fallbacks visible (logged) and stop substituting load values for temperature.

**Non-Goals:**
- No retraining-architecture change (quantiles stay three independent LightGBM models; we repair, not re-formulate).
- No change to the physical plan, nor to the Open-Meteo baseline values themselves (only how single missing slots within a good fetch are filled — D7).
- #11 (`print()` → logger) is out of scope (belongs to `harden-ci-and-tests`). A whole-fetch Open-Meteo outage is out of scope — already handled upstream by reusing the last successful stored fetch.

## Decisions

**D1 — Sample-weight alignment by label, not position (#15).** Today `_compute_sample_weights` returns `.values` (a positional numpy array) but is indexed with the gapped pandas label index after `dropna(subset=["slot_start"])`. Fix: after the dropna/sort that builds the training frame, `reset_index(drop=True)` so the label==position invariant holds before weights are computed and sliced. *Alternative considered:* return a label-indexed `Series` and use `.reindex`/`.loc`. Rejected as the primary fix because it spreads alignment logic across call sites; the reset-index approach fixes it once at the source. We still convert the weight access to be label-safe as defense.

**D2 — Force weather columns in training, validate feature names at load (#16).** Inference always builds the 3 weather columns "to match trained model feature count"; training only adds `temp_c` when `weather_df` is empty. Fix: training materialises all 3 weather columns (NaN-filled) exactly as inference does, so `feature_cols` is identical regardless of weather availability. Defense-in-depth: persist the trained feature-name list and validate it at `_load_models`, failing loud (and falling back to baseline) on mismatch rather than mis-mapping columns. *Alternative:* only validate at load. Rejected — that detects the bug but still loses a usable model; making training symmetric prevents it.

**D3 — Post-hoc monotonic repair of quantiles (#17).** Sort the three per-slot outputs to enforce `p10 ≤ p50 ≤ p90` at the single write point in `forward.py` (load and PV), and apply the same cheap repair defensively on read (`ml/api.py`) so any historical crossed rows are also corrected before the planner or the daily aggregation (`forecasts.py`) sees them. *Alternative:* train with a monotone/joint formulation. Rejected for this change — it is a larger modelling change; sorting is exact, cheap, and needs no retraining.

**D4 — Evaluation mirrors the live residual pipeline (#18).** `evaluate.py` must build the same feature set as `forward.py` (including `physics_forecast_kwh`), add the Open-Meteo baseline back to the residual prediction, and score all quantiles — reusing the inference feature-building helper rather than a parallel copy. *Alternative:* leave evaluation as-is and document it as approximate. Rejected — the number is shown to users as "PV forecast quality" and currently scores `actual − openmeteo` as if absolute, which is misleading, not merely approximate.

**D5 — Neutral default for missing temperature (#9).** In the `baseline_7_day_avg` aggregation, when `temp_c` is absent, fill with `NaN` (a neutral missing value) instead of `("load_kwh", "mean")`. Downstream consumers already tolerate missing temperature; they must never receive load magnitudes disguised as temperatures.

**D6 — Fail loud on missing ML inputs (#10).** The config-load and HA context-feature fetches keep their fallback (return empty/default so the forecast still runs) but emit a `logger.warning` describing what was lost, and narrow the `except Exception` to the expected error types where practical. Degraded forecasts become diagnosable instead of silent.

**D7 — Interpolate Open-Meteo gaps; drop the home-grown fallback (OQ5).** When the Open-Meteo baseline is NaN for a slot within an otherwise-successful fetch (`ml/forward.py:385–394`), fill it by linear interpolation between the nearest valid Open-Meteo slots on either side; if no valid neighbour exists (a leading/trailing run of NaN), use 0. This replaces the per-slot fallback to the home-grown physics, which over-produces ~2.5× and is bounded only by the physical ceiling. *Alternatives considered:* carry-last-good (rejected — a stale value misleads at sunrise/sunset edges); keep-physics (rejected — it is the very over-production `pv-open-meteo-baseline` set out to remove); zero-everything (rejected — understates daytime gaps, making the planner needlessly cautious). The home-grown physics survives only as a display-only output (`physics_kwh`); the model feature `physics_forecast_kwh` already equals the Open-Meteo baseline, so no feature change is needed.

## Risks / Trade-offs

- **Quantile sort silently changes stored band values** → only reorders already-invalid (crossed) values into a valid order; add a unit test asserting monotonicity and that non-crossed bands are untouched.
- **NaN weather columns at training time confuse LightGBM** → LightGBM handles NaN natively; covered by a train-during-outage-then-infer test (D2).
- **Reported forecast-quality numbers will shift when D4 lands** → expected and correct (they move from a meaningless basis to the real one); call this out in release notes so it isn't read as a regression. Diagnostic-only — no planning impact.
- **Feature-name validation could reject a previously-served model** → that model was already mis-mapping columns; falling back to the Open-Meteo baseline is the safe behavior. Logged loudly.

## Migration Plan

No data migration. No schema or config change. On deploy: the next nightly training run produces a symmetric-feature model; quantile repair takes effect on the next inference and on read for existing rows; the evaluation change takes effect on the next quality computation. Rollback is a plain code revert with no state to undo.

## Open Questions

None. OQ5's remaining piece (the per-slot home-grown physics NaN-fallback) is decided here by D7 — interpolate from neighbouring Open-Meteo slots. No outstanding decisions.
