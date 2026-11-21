# Proposal

## Why

Three independent defects share one release. The D+1 price forecast fallback loses the 00:00 slot at the Nordpool/forecast boundary, so the schedule jumps from 23:45 to 00:15. The daily battery benchmark stores days as failed when recorded reality exceeded the limits the strict hindsight solve enforces. Dead error-correction config keys and model files remain on user installs long after the corrector was removed.

## What Changes

- Price forecast generation builds each forecast day half-open, giving 96 slots (92 and 100 on DST days), so the next day's 00:00 is no longer stored twice.
- The D+1 forecast fallback selects tomorrow's slots by target local date from the latest issue per slot, regardless of `days_ahead`, instead of `days_ahead=1` with a row limit. This also fixes the missing fallback between 00:00 and the daily issue (tomorrow is then stored as `days_ahead=2`) and tolerates duplicate rows already stored in user databases. Each fallback slot carries `forecast_days_ahead` into the planner price data. No migration and no schema change.
- **Behaviour change:** the planner sees tomorrow's forecast prices from 00:00 (forecast up to about a day old) instead of from the daily issue, so the horizon no longer jumps at 06:00.
- The battery benchmark keeps its strict solve first. When that is infeasible, it re-solves once with grid import, grid export, inverter AC and export-floor limits relaxed to what was recorded, and scores the day with a `limits_relaxed` warning that names the relaxed limits. If the relaxed solve also fails, the day is stored as failed with a specific reason instead of `solver_not_optimal`.
- `BENCHMARK_VERSION` is bumped to 3 so the new record field is present on every stored day in the 14-day window.
- The benchmark card shows a human label for `limits_relaxed`, and the specific failure reason.
- Config migration removes `learning.error_correction_enabled`, `learning.auto_tune_enabled` and `automation.ml_training.error_correction_enabled`.
- `ml/models/defaults/load_error.lgb` is deleted from the repo. Startup model bootstrap idempotently deletes `pv_error.lgb` and `load_error.lgb` from the runtime models directory, its `defaults/` copy and the training backups.
- `scripts/health_check.py` stops reporting the two files as optional models.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `price-forecasting`: forecast days contain exactly one slot per local 15-minute slot, and the D+1 fallback is selected by target date.
- `daily-battery-benchmark`: infeasible strict solves are retried with recorded limits and scored with a `limits_relaxed` warning; specific failure reason; version bump.
- `aurora-corrector`: stale `*_error.lgb` files are purged at startup and the dead config keys are removed.
- `config-dead-key-removal`: the three error-correction and auto-tune keys are removed by migration.

## Impact

- Code: `ml/price_features.py`, `ml/price_forecast.py`, `backend/core/prices.py`, `backend/battery_benchmark.py`, `planner/solver/kepler.py` and `planner/solver/types.py` (benchmark mode only), `backend/config_migration.py`, `ml/bootstrap.py`, `scripts/health_check.py`, `frontend/src/components/CommandDomains.tsx`, `frontend/src/lib/api.ts`.
- Removed file: `ml/models/defaults/load_error.lgb`.
- Planning and control are unaffected: live Kepler never runs in benchmark mode.
- No new dependencies, no DB schema change, no `CURRENT_CONFIG_VERSION` bump. HA add-on options are unaffected.
- Scope boundary: price reserve logic belongs to `price-reserve-forecast-accuracy`. This change only touches the slot generation and the D+1 fallback read in `ml/price_forecast.py`.
