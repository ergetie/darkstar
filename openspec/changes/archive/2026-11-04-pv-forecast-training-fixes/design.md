# Design

## Context

Evidence and scripts: `debugging/pv-overforecast-2026-11/` (backtests `bt_*.py`). Verified code locations (several differ slightly from the investigation notes):

- `ml/train.py:365` `get_weather_series(obs_start, now, ...)`; `ml/weather.py:358-370` uses the forecast API with `past_days=1`, so history is NaN.
- `ml/train.py:463-470`: the PV filter is `radiation > 10 OR pv > 0.01` and only runs when the radiation column exists; with NaN weather only `pv > 0.01` slots survive. Training SQL in `_load_slot_observations` (`ml/train.py:~108-175`, four branches) selects only `load_kwh`, `pv_kwh`, baseline, and filters spikes with `get_max_energy_per_slot` (`backend/validation.py:17`, grid power x 0.5 h x 2).
- `ml/forward.py:~676` writes `pv_ml_residual_raw_kwh`; `bin/run_planner.py:~73` re-upserts `forecast_data` built at `backend/core/forecasts.py:~366-376` (field omitted); `backend/learning/store.py:468` sets the column to `excluded` (NULL), unlike `openmeteo_pv_forecast_kwh` (`store.py:464-467`, COALESCE).
- `backend/learning/pv_openmeteo_backfill.py:36-37` uses `or 30.0` / `or 180.0`; live path `backend/core/forecasts.py:539-551` does not.
- `backend/learning/reflex.py:39` `CONFIDENCE_BIAS_THRESHOLD = 0.5`; bias input is `store.get_forecast_vs_actual` (`store.py:833`) which keeps only `actual > 0.01`.
- `backend/health.py` `HealthChecker.check_all` aggregates `HealthIssue` objects (category, severity, message, guidance) that the UI already shows.
- `ml/forward.py:61` `_total_solar_kwp`; `ml/weather.py:27` `_calculate_solar_position` (NOAA elevation).

Walk-forward backtests on 4 sites showed historical weather best or tied on 3 of 4 (prod cloudy-day bias +15 % to +1.3 %; days off by more than 30 %: prod 28.0 to 22.3, kristofer 19.8 to 12.1, pll 18.2 to 13.0; torleif neutral with 7 weeks of data).

## Goals / Non-Goals

**Goals:** populate weather features in training; clean PV data so the model learns shading but not artefacts; make Reflex confidence work; stop two silent data-loss bugs; warn users of implausible PV measurement.

**Non-Goals:** multiplicative/ratio target, sun elevation/azimuth features, per-bin ratio table (all tested, no gain); changing `pv_residual_bound_fraction` (stays 1.0); intraday correction; schema changes; new config keys.

## Decisions

### D1. Historical weather source and shape
Add `get_historical_weather_series(start, end, config)` in `ml/weather.py`. It requests `https://historical-forecast-api.open-meteo.com/v1/forecast` (hourly `temperature_2m,cloud_cover,shortwave_radiation`, `start_date`/`end_date`, location and timezone from config), and for dates the endpoint returns no data for falls back to `https://archive-api.open-meteo.com/v1/archive`. It reuses the existing parsing, DST-safe localize, duplicate drop and 15-minute linear resample code, factored out of `get_weather_series` into one shared helper so both paths produce identical columns. Data is requested with `timezone=UTC` and cached per UTC day (DST changes then cannot duplicate or shift instants; the merged UTC frame is converted to the planner timezone at the end, and trailing quarter-hours of the last hour are forward-filled by at most 3 slots so the last day is complete). Cache: per-day in-memory dict keyed by (lat, lon, UTC date, source) with a long TTL (completed past days do not change; today and yesterday use the existing 1 h TTL), plus the existing request retry helper. `train.py` calls it instead of `get_weather_series`. `ml/evaluate.py:414` keeps its call (evaluation mirrors inference). Alternative rejected: archive only (reanalysis differs from the forecast the model sees live).
- Failure: a failed or empty fetch returns an empty frame; `train.py` logs a warning and trains without the weather columns (optional-feature loop at `train.py:~417` already skips absent columns).
- Forecast too high/low: not applicable to fetching; if historical and live weather disagree with reality, the model sees the same kind of error in training as live.

### D2. One shared cleaning function
New `backend/learning/pv_cleaning.py` with `clean_pv_slots(df, *, total_kwp, latitude, longitude) -> pd.DataFrame` (pure, vectorised) over columns `slot_start` (tz-aware), `pv_kwh`, `baseline_kwh`, optional `soc_end_percent`, `export_kwh`. Rules, in order, evaluated on the original rows and combined with OR into a drop mask:
1. keep only `baseline > 0.01`;
2. dropout: `pv == 0 and baseline > 0.3`;
3. spike: `pv > total_kwp * 0.25 * 1.05` (skipped if total_kwp <= 0), or `pv > 0.05` and sun elevation < -3 degrees at slot mid-point (UTC, via `_calculate_solar_position`; skipped if no location);
4. curtailed: `soc >= 97 and export < 0.02 and baseline > 0.05` (skipped per row if either is null).
Constants are module-level, named, unit-tested. All thresholds are fractions or physical quantities derived from the site's own kWp, location and measurements; no per-user values. Both `train.py` and `get_forecast_vs_actual` use it. Existing `get_max_energy_per_slot` filter stays in the SQL as an outer sanity bound. `_load_slot_observations` is extended to select `soc_end_percent` and `export_kwh` in all four branches. The `radiation > 10` sun-up mask is removed (superseded by `baseline > 0.01`). Drop counts per rule are printed at INFO.
- Forecast too high: slots where PV is far below baseline are kept (residual strongly negative) unless the dropout/curtailment rules mark them as measurement faults. Forecast too low: slots with PV above baseline are kept up to the physical cap (kWp x 0.25 x 1.05).

### D3. Reflex bias input
`get_forecast_vs_actual(target="pv")` additionally selects `SlotForecast.openmeteo_pv_forecast_kwh`, `SlotObservation.soc_end_percent`, `export_kwh`, drops the SQL `actual > 0.01` condition, and applies `clean_pv_slots`; it needs `total_kwp` and location, so it takes them as arguments from the caller (Reflex reads them from config via the same helpers as training; `_total_solar_kwp` moves to `backend/learning/pv_cleaning.py` as the public `total_solar_kwp`, next to a `site_location(config)` helper returning latitude/longitude with the weather code's defaults; `ml/forward.py` imports it). The `error` column stays forecast minus actual. Load target path unchanged.

### D4. Relative-bias Reflex
In `analyze_confidence`: `rel_bias = (forecast.sum() - actual.sum()) / actual.sum()` (returns "Confidence: Stable (no production in window)" with no change if the actual sum is 0). Replace `CONFIDENCE_BIAS_THRESHOLD` with `CONFIDENCE_REL_BIAS_THRESHOLD = 0.10`. Over: lower confidence by `MAX_DAILY_CHANGE`; under: raise it; clamped by `BOUNDS` (70-120) as before. Report strings show percent. The +/-10 % dead band is the hysteresis that stops oscillation; confidence is a safety margin, not the bias fix (training is). Because the stored forecast already includes the current confidence, repeated moves converge when bias falls inside the band.

### D5. Raw residual persistence
`store.py:468` becomes `func.coalesce(stmt.excluded.pv_ml_residual_raw_kwh, SlotForecast.pv_ml_residual_raw_kwh)`. This alone fixes the overwrite: the planner's re-upsert omits the field (NULL), and the COALESCE keeps the stored value. No passthrough in `backend/core/forecasts.py` is needed or added: `get_forecasts_range` does not select the column, so `db_slot` never carries it and a passthrough would always be None. Trade-off: an intentional reset to NULL is impossible through upsert (none exists today).

### D6. Backfill tilt/azimuth
In `_valid_arrays`, replace `or` chains with a small helper `_num(value, default)` returning `default` only when value is None (or not numeric), then apply the existing `% 360 - 180` azimuth conversion.

### D7. Site sanity notice (informational)
New `backend/learning/pv_site_sanity.py`: `async compute_pv_site_ratio(store, config, days=60) -> (ratio, clear_day_count) | None` over the same cleaned slots as D2 (data from a new store method `get_pv_actual_vs_baseline(days_back)`). Clear day: daily baseline sum >= 75 % of the window's highest daily baseline and >= 1 kWh; >= 14 clear days required, else None. `HealthChecker.check_pv_site_sanity()` (async, added to `check_all`) caches the ratio for 6 hours in a module variable (a failed computation is cached as no evidence for 10 minutes so polling does not hammer the database), never raises (debug log), and emits a `HealthIssue` with severity `info`, category `forecast`, code `pv_site_ratio_low` or `pv_site_ratio_high`, and a new optional field `acknowledge_id` equal to the code.
Decisions (confirmed by the user): band 0.55-1.30; the clear-day definition above; per-day weather cache (D1). The originally suggested 0.8-1.2 band would warn on nearly every site because the raw baseline is optimistic (measured actual/baseline on clear days 0.65-0.93 across 4 sites, none with a known fault).
Heavy shading, especially in winter with a low sun, can legitimately push the ratio below 0.55 on a correctly configured site. That is why the notice is informational and dismissible, and why the wording suggests possible causes rather than asserting a fault.
Wording (percentage X rounded to a whole number):
- Low, message: "Your solar panels produce much less than forecast on clear days (about X % of forecast)." guidance: "This can be shading, a wrong panel setting, or a missing string. Darkstar still learns and adjusts the forecast."
- High, message: "Your solar panels produce much more than forecast on clear days (about X % of forecast)." guidance: "This can be panels set up smaller than they really are, or production measured twice. Darkstar still learns and adjusts the forecast."

### D8. Acknowledge rule and persistence
Existing mechanisms reviewed: the UI banner snooze (`SystemAlert`, 24 h, `localStorage`, per browser, stores no value) and `data/onboarding_state.json` `dismissed_notices` (`backend/core/onboarding_state.py`, server-side, atomic write, stores ids only). Neither stores the acknowledged ratio. Decision: add a field `acknowledged_warnings: dict[NoticeId, float]` (id -> ratio at acknowledgement) to `OnboardingState` in the same JSON file. This is a file, not a database schema change; old files load because the field has a default, and `write_state` preserves it like `dismissed_notices`. One installation is one site, so the file is per site.
- `acknowledge_warning(id, ratio)` persists via the existing `_persist`; `POST /api/system/health/acknowledge` with `{id}` records the ratio currently cached by the sanity check (409 if there is no active notice for that id, so the frontend never supplies the value).
- Suppression rule applied server-side in `check_pv_site_sanity`: with acknowledged ratio `r0` and current ratio `r`: low side (r0 < 0.55) shows again if `r <= r0 - 0.10` or `r > 1.30`; high side (r0 > 1.30) shows again if `r >= r0 + 0.10` or `r < 0.55`; otherwise hidden. Acknowledgements are stored per notice id (`pv_site_ratio_low` / `pv_site_ratio_high`). When `r` is inside 0.55-1.30 both stored acknowledgements are removed (so a later recurrence is shown); when the ratio is out of band on one side, the acknowledgement of the opposite id is removed. Improvement without leaving the band edge is not a reason to reshow.
- Ratio too low or too high are handled symmetrically; both are informational.
- Frontend: `SystemAlert` renders `info` issues only when they carry `acknowledge_id`, using the existing `banner banner-info` classes and a `btn btn-ghost` "Got it" button (same pattern as `ProfileSetupNotice`); clicking calls the new API and removes the issue locally; the existing 24 h snooze and collapse stay for warnings and errors. Other `info` issues stay hidden as today. No new components or colours; per `docs/design-system/AI_GUIDELINES.md`, banners and button classes only.

## Risks / Trade-offs

- [Open-Meteo historical-forecast API coverage starts 2022 and has gaps] -> archive fallback per missing date; failure degrades to no weather with warning.
- [First training after upgrade changes forecasts] -> models are retrained by existing schedule; backtests support improvement; torleif-like sites with little data stay neutral.
- [Dropping curtailed slots hides high-SoC sunny periods from training] -> intended: those measurements understate potential; bias toward lower forecasts on such days is avoided.
- [Keeping zero slots could teach false zeros if a sensor is down] -> dropout rule (baseline > 0.3) removes the large cases; small ones are indistinguishable from shade.
- [Reflex now fires] -> bounded to 70-120 %, 5 points/day, once a day, 14-day window, dead band 10 %.
- [Sanity check cost] -> one query per 6 hours.

## Migration Plan

No schema or config changes. Deploy, then retrain (scheduled or manual) to produce weather-aware models. Rollback: revert the commit; old models remain loadable (feature list is stored with each model; inference already tolerates the same feature names).

## Open Questions

None blocking. Sites with fewer than 14 clear days in 60 get no notice by design.
