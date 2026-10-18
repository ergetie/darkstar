## Why

When Open-Meteo is unreachable, `_get_forecast_data_async()` (backend/core/forecasts.py:370, except at :518) falls back to `_get_stored_openmeteo_pv_for_slots()` (:28-64). That helper returns `None` if ANY price slot lacks a stored value (:60-61), so the fallback is all-or-nothing. Stored coverage typically ends ~3 days ahead (`learning.horizon_days` default 3), so a longer horizon, a fresh install or a data gap raises `PVForecastError` (:532) and users see "PV Forecast Failed: ... The API is unreachable | Solar arrays: 4". Confirmed in code only; not reproduced (logs rotated).

Effect on planning depends on the forecast mode. Non-Aurora / `aurora_pv_enabled: false`: `PVForecastError` propagates out of `get_all_input_data()` -> `bin/run_planner.py:51` -> `planner_service.py`, the run fails and the old schedule stays (executor holds once it is older than `max_schedule_age_hours`, see design.md). Default Aurora mode: the error is swallowed in `ml/forward.py:216-218`, which substitutes a zero baseline, so inference stores zero-PV forecasts and the planner plans with zero solar while the banner shows the failure (design.md Q1b). This change fixes that path too.

## What Changes

- Make the stored-forecast fallback partial: use stored slots where present, estimate the missing ones.
- Estimate for a missing slot = value of the most recent stored slot with the same local time of day (latest stored day wins). No same-time-of-day value anywhere -> slot counts as unusable and the whole fallback fails (all-or-nothing).
- Mark the forecast degraded with the number of estimated slots; banner text "API unreachable — using last known forecast (N slots estimated)".
- Still raise `PVForecastError` (critical) when no usable stored data exists; Aurora inference must then abort without storing instead of using a zero baseline (ml/forward.py).
- Treat an empty Open-Meteo estimate as a failure; never default missing slots to 0.
- Estimated slots are never persisted as stored Open-Meteo baselines.
- Planner Aurora/DB path (`build_db_forecast_for_slots`): slots beyond stored coverage no longer repeat the last stored slot (which could carry a night-time zero into daytime) or default to 0; PV uses the same-time-of-day estimate, shares the helper above, and is flagged/counted/reported as degraded. No stored rows at all records a critical error.
- Out of scope: same-day correction from actual production (rejected).

## Capabilities

### New Capabilities

### Modified Capabilities
- `executor`: stale-schedule default age is 2 h (was 6).
- `open-meteo-pv-forecast`: partial stored fallback and no-silent-zero rules.
- `pv-forecast-source-indicator`: outage banner text and severity.

## Impact

- backend/core/forecasts.py (fallback helper, except block, zero defaults)
- executor/config.py (`max_schedule_age_hours` default 6 -> 2), `executor` spec stale-schedule requirement, tests/executor/test_executor_safety.py
- ml/forward.py (`_fetch_openmeteo_baseline_series`, stored baseline column)
- backend/health.py (`record_forecast_error`, `check_forecast` ~:942-975: degraded message includes estimated count)
- No change to backend/api/routers/system.py (estimated count is not exposed there)
- tests/ml/test_forecast_aggregation.py, tests/ml/test_db_forecast_gap_fill.py
