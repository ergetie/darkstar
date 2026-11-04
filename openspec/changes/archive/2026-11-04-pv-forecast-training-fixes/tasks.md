# Tasks

Conventions for every test below: pin dates (for example 2026-06-15 for summer, 2026-03-29 and 2026-10-25 for DST days in Europe/Stockholm), build full-day frames of 96 quarter-hour slots (92 and 100 on DST days), never use `datetime.now()` unpinned. Run with `UV_NO_SYNC=1 uv run python -m pytest <file> -v`.

## 1. Raw residual persistence

- [x] 1.1 In `backend/learning/store.py` (upsert `set_`, line ~468) wrap `pv_ml_residual_raw_kwh` in `func.coalesce(stmt.excluded..., SlotForecast.pv_ml_residual_raw_kwh)`. Verified by 1.3.
- [x] 1.2 (Dropped) A `forecast_data` passthrough in `backend/core/forecasts.py` is unnecessary: `get_forecasts_range` does not select the column, so it would always be None. The COALESCE in 1.1 is the fix (design D5).
- [x] 1.3 Add `tests/ml/test_residual_raw_persistence.py`: (a) store a row with residual 0.12, upsert the same slot without the field, assert 0.12 remains; (b) upsert with 0.30, assert 0.30.

## 2. Backfill tilt and azimuth

- [x] 2.1 In `backend/learning/pv_openmeteo_backfill.py` `_valid_arrays` replace the `or 30.0` / `or 180.0` with a helper that defaults only on None or non-numeric, keeping the `% 360 - 180` azimuth conversion. Verified by 2.2.
- [x] 2.2 Extend `tests/ml/test_pv_openmeteo_backfill.py`: tilt 0 stays 0; azimuth 0 yields -180 (north), azimuth 180 yields 0; missing tilt/azimuth yield 30 and 0 (south); null values yield defaults.

## 3. Shared PV cleaning

- [x] 3.1 Create `backend/learning/pv_cleaning.py` with named constants and `clean_pv_slots(df, *, total_kwp, latitude, longitude)` implementing design D2 (baseline > 0.01 keep; dropout pv == 0 and baseline > 0.3; spike pv > kWp x 0.25 x 1.05 or pv > 0.05 with sun elevation < -3 degrees; curtailed SoC >= 97 and export < 0.02 and baseline > 0.05; rules skipped when their inputs are missing). Move `_total_solar_kwp` here from `ml/forward.py` and import it back in `ml/forward.py`. Verified by 3.2.
- [x] 3.2 Add `tests/ml/test_pv_cleaning.py` using 2026-06-15 (96 slots, lat 59.3 lon 18.1, kWp 10): shaded zero slot with baseline 0.2 kept; night slot baseline 0 dropped; dropout (pv 0, baseline 0.45) dropped; pv 0, baseline 0.2 kept; pv 2.8 dropped and 2.6 kept (limit 2.625); pv 0.1 at 02:00 local dropped; curtailed (SoC 100, export 0, baseline 0.4) dropped, same row with SoC NaN kept, with export 0.5 kept; kWp 0 skips spike rule; pv far above baseline but below cap kept; result identical on a 2026-03-29 (92 slots) and 2026-10-25 (100 slots) frame in terms of expected kept count.
- [x] 3.3 In `ml/train.py` `_load_slot_observations` add `o.soc_end_percent` and `o.export_kwh` to the SELECT of all four query branches (keep the existing `max_kwh` filters). Verified by 3.5.
- [x] 3.4 In `ml/train.py` PV section (~463-470) delete the radiation/pv sun-up mask and call `clean_pv_slots` (kWp via `_total_solar_kwp(engine.config)`, location resolved as in `ml/weather.py`) before dropping rows with missing baseline; print the dropped count per rule. Verified by 3.5.
- [x] 3.5 Extend `tests/ml/test_training_quality_filter.py` with an in-memory learning DB for 2026-06-15: assert training PV rows include the zero-PV shaded slot and exclude the dropout, spike, night and curtailed slots, and that the load training rows are unchanged.

## 4. Historical weather in training

- [x] 4.1 In `ml/weather.py` factor the hourly-payload to 15-minute DataFrame code (parse, DST-safe localize, duplicate drop, resample) out of `get_weather_series` into one helper used by both functions. Verified by existing `tests/weather` passing unchanged.
- [x] 4.2 In `ml/weather.py` add `get_historical_weather_series(start_time, end_time, config=None)`: historical-forecast API first, archive API for dates it does not return, per-day cache (completed days long TTL, today and yesterday 1 h), existing retry helper, empty DataFrame on any failure with a logged warning. Verified by 4.4.
- [x] 4.3 In `ml/train.py` (~365) replace `get_weather_series(obs_start, now, ...)` with `get_historical_weather_series`; when the frame is empty print a warning that training continues without weather. `ml/evaluate.py` is not changed. Verified by 4.4.
- [x] 4.4 Add `tests/weather/test_historical_weather.py` with mocked `requests.get`: 3 pinned days (2026-06-14..16) return 72 hourly values and the result has 288 slots, 15-minute spaced, with all three columns; a window containing 2026-10-25 has no duplicated or missing instants; a second call makes no request; archive fallback is used when the historical-forecast response lacks a date; request failure returns an empty frame and a warning. Also a `tests/ml` test that `train_models` with the fetch mocked to empty still saves PV and load models.

## 5. Reflex relative bias

- [x] 5.1 In `backend/learning/store.py` `get_forecast_vs_actual`: for `target="pv"` select baseline, SoC and export, remove the SQL `actual > 0.01` condition, accept `total_kwp`, `latitude`, `longitude` arguments and apply `clean_pv_slots`; keep the `error` column as forecast minus actual; the load path stays unchanged. Verified by 5.4.
- [x] 5.2 In `backend/learning/reflex.py` replace `CONFIDENCE_BIAS_THRESHOLD` with `CONFIDENCE_REL_BIAS_THRESHOLD = 0.10`; in `analyze_confidence` compute `(forecast.sum() - actual.sum()) / actual.sum()` (no-production message when the actual sum is 0), pass kWp and location to the store call, keep `BOUNDS`, `MAX_DAILY_CHANGE`, minimum samples and the rate limit, and print percentages in the report strings. Verified by 5.4.
- [x] 5.3 Update any callers of the old constant (`rg CONFIDENCE_BIAS_THRESHOLD`) and the existing assertions in `tests/ml/test_reflex.py` that use kWh/slot.
- [x] 5.4 In `tests/ml/test_reflex.py` add cases on pinned 14 days (2026-06-01..14, 96 slots each): bias +15 % lowers confidence by 5 (from 90 to 85); -15 % raises it by 5; +6 % no change; at lower bound 70 stays 70; at upper bound 120 stays 120; fewer than 100 samples no change; actual sum 0 no change; a day with curtailed slots does not change the measured bias; two arrays sizes with identical relative bias behave the same.

## 6. Site sanity notice

- [x] 6.1 Add store method `get_pv_actual_vs_baseline(days_back)` in `backend/learning/store.py` returning slot_start, actual, baseline, SoC, export, and create `backend/learning/pv_site_sanity.py` with `compute_pv_site_ratio` (60-day window, clear day = daily baseline >= 75 % of window max and >= 1 kWh, >= 14 clear days else None, cleaned slots). Verified by 6.4.
- [x] 6.2 In `backend/health.py` add optional `acknowledge_id: str | None` to `HealthIssue` (included in `to_dict` only when set). Add async `check_pv_site_sanity` (6-hour module cache of the ratio, fail-open with debug log) emitting one `info` issue in category `forecast`, code `pv_site_ratio_low` or `pv_site_ratio_high`, `acknowledge_id` equal to the code, when the ratio is below 0.55 or above 1.30, with the exact wording from design D7; call it from `check_all`. Verified by 6.4.
- [x] 6.3 In `backend/core/onboarding_state.py` add `acknowledged_warnings: dict[NoticeId, float]` (default empty, max 100 entries) to `OnboardingState`, preserve it in `write_state`, add `acknowledge_warning(id, ratio)` and `clear_acknowledged_warning(id)` using `_persist`. In `check_pv_site_sanity` apply the design D8 suppression rule and clear the acknowledgement when the ratio is inside the band. Verified by 6.4 and 6.5.
- [x] 6.4 Add `tests/health/test_pv_site_sanity.py` on a pinned 60-day window ending 2026-06-30 (96-slot days): ratio 0.40 over 20 clear days gives the low info notice with "about 40 %"; 1.50 gives the high notice; 0.8 gives none; boundaries 0.55 and 1.30 give none; 9 clear days gives none; a store error gives no issue and no exception; a second call within 6 hours does not query again; messages contain none of the words error, failed and no technical identifiers; severity is `info`. Acknowledgement cases with a temporary state file: acknowledged 0.40 then 0.38 hidden; then 0.30 shown; 0.50 hidden; 1.40 shown; acknowledged 1.50 then 1.58 hidden, 1.60 shown, 0.50 shown; ratio returns to 0.80 clears the entry and a later 0.45 shows the notice; old state file without the new field loads; `write_state` keeps acknowledgements.
- [x] 6.5 In `backend/api/routers/system.py` add `POST /api/system/health/acknowledge` with body `{id}` (validated `NoticeId`, `extra="forbid"`): stores the currently cached ratio for that id via `acknowledge_warning`, returns 200 with the id; returns 409 and stores nothing when no notice is active for the id. Add `tests/api/test_health_acknowledge.py`: success persists the ratio, 409 without an active notice, invalid id rejected with 422, repeated calls overwrite the ratio.

## 7. Frontend acknowledge

- [x] 7.1 In `frontend/src/lib/api.ts` add `acknowledge_id?: string | null` to the health issue type and `Api.acknowledgeHealthIssue(id)` (top-level, next to `Api.health`) posting to `/api/system/health/acknowledge`. In `frontend/src/components/SystemAlert.tsx` add the same optional field to `HealthIssue`, and render `info` issues that have `acknowledge_id` as `banner banner-info` with message, guidance and a `btn btn-ghost` "Got it" button that calls the API and removes the issue locally; failures log to console and keep the banner. Other `info` issues stay hidden and critical/warning rendering and snooze are unchanged. Verified by 7.2.
- [x] 7.2 In `frontend/src/components/SystemAlert.test.tsx` add cases: an info issue with `acknowledge_id` renders with the info banner class and its text; clicking "Got it" calls `acknowledgeHealthIssue` with the id and hides it; an API failure keeps it visible; an info issue without `acknowledge_id` is not rendered; existing snooze tests still pass.

## 8. Verification

- [x] 8.1 Run `./scripts/lint.sh`, `pnpm` frontend lint/typecheck/tests and the new and touched test files; all pass with no new lint or type errors.
- [x] 8.2 Run `openspec validate pv-forecast-training-fixes --strict`; it reports valid.
