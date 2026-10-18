## Context

Current flow: API exception (forecasts.py:518) -> `_get_stored_openmeteo_pv_for_slots` -> `None` if any slot missing -> `PVForecastError`. `record_forecast_error` (health.py:42) sets status "degraded" for non-PV errors, "error" for `PVForecastError`; `check_forecast` (health.py:942) turns "error" into a critical banner and "degraded" into a generic warning.

## Decisions

1. Helper returns `(values, daily, estimated_slot_indices)` or `None` when any slot cannot be filled (no stored baseline and no same-time-of-day value in the lookup window); a partial forecast with unfillable slots is never returned, so zero is never planned silently. Missing slots: same local time-of-day from the latest stored day before the slot, else the earliest stored day after it. Lookup window: stored baselines from 14 days before the first price slot to the end of the horizon (module constant; matches `forecasting.pv_personalization_ramp_days` default 14). Stored NULL is already excluded by the query (store.py:811); a stored 0.0 is a legitimate night/zero value. Rationale: stored data already holds the shape of recent clear/cloudy production, no new dependency, deterministic. Slightly optimistic or pessimistic vs real weather; it is flagged as an estimate.
2. Rejected: ML-only values (not guaranteed to exist for the same gap), zero fill (hides outage), same-day correction from actuals (rejected by user).
3. Status: record a non-`PVForecastError` error with context `{estimated_slots: N, fallback: "last_known_openmeteo"}`, giving "degraded". `check_forecast` builds the message from the latest entry's `estimated_slots` instead of the generic text. Existing message "API unreachable — using last known forecast" is retained as the prefix.
4. Daily totals (`daily_pv_forecast`) are recomputed from the filled values so downstream day totals stay consistent.
5. Failure path unchanged (critical `PVForecastError`, planner run aborts and previous schedule stays).

6. Planner DB path: `build_db_forecast_for_slots` fetches stored rows from 14 days before the horizon (same constant) and fills uncovered PV via `_estimate_from_same_time_of_day`; 1-2 slot interior gaps are linearly interpolated (`_interpolate_small_pv_gaps`). Slots carry `pv_estimated`; `_get_forecast_data_aurora` records a degraded error (`estimated_slots`, `total_slots`) when PV is Aurora-driven. Non-PV fields (load, load p10/p90) keep the previous carry-forward (`_get_forecast_data_aurora` already replaces load <= 0.001 with the HA profile); PV p10/p90 are None for estimated slots. With no stored rows the function still returns `[]` (planner gets no slots); this is a fresh-install/learning-period state (the forward job has not written rows yet) and is logged at info level only, never recorded as a health error or banner. Degraded/critical reporting is reserved for real outages: stored data exists but a refresh failed, or the Open-Meteo fetch failed. The 50% critical escalation therefore only applies to those outage cases. Planner control flow is unchanged (empty slots on a brand-new install is pre-existing behaviour; a direct Open-Meteo fallback would be a separate decision).

## Risks

- Estimates can be wrong for several days; mitigated by the visible degraded banner and the 50% critical escalation. No hard cap and no "give up after N hours" rule in Aurora mode (user decision): estimated slots are still used (stale-but-shaped beats aborting). The 50% threshold (confirmed) is a module constant.

## Resolved questions

### Q1. What happens to the kept schedule as it ages? (evidence)

Executor tick (executor/engine.py:1636-1652 -> `_load_current_slot` 2330-2440):
- Within `max_schedule_age_hours` the executor keeps following the old schedule normally (engine.py:2383-2394 only rejects when `now - meta.generated_at > max`). `generated_at` is written only by a successful planner run (planner/output/schedule.py:90-92), so a failing planner never refreshes it.
- Age limit (before decision Q3): code default 6 h (executor/config.py:340, :1095; spec "Executor rejects a stale schedule and holds"), but the shipped `config.default.yaml:399` sets 2 h. Effective limit is therefore 2 h on installs that inherit the shipped default, 6 h only if the key is absent. Planner cadence is `config.default.yaml:229` every 30 min, so ~4 consecutive failures (2 h) reach the limit.
- Past the limit, or when the schedule has no slot for "now" (schedule horizon ended, 2400-2438), `_load_current_slot` returns `None`; `slot_exists/slot_valid=False` (engine.py:1659-1660) -> `OverrideEvaluator` SLOT_FAILURE_FALLBACK (override.py:168-182): `grid_charging=False`, `soc_target = current SoC`, `water_temp = water_temp_off`. One error notification per fresh->stale transition (engine.py:1646-1650).
- Battery: `_apply_override` (controller.py:150+) writes idle intent, no grid charging, SoC held. EV: `slot=SlotPlan()` (engine.py:1816-1817) has empty `ev_charger_plans` and `ev_keep_on`, so `_charger_should_be_on` is False unless a manual charge is active (engine.py:4108-4121) and the charger is switched off. Water: heater target forced to `water_temp_off`.
- No path in the executor plans or substitutes a zero-PV plan; it only holds. Aging the old schedule therefore cannot, by itself, produce "plans as if zero solar" (it produces an idle hold after 2 h / 6 h).
- Spec/behaviour verdict: hold behaviour matches the executor spec. Decision (user): `max_schedule_age_hours` = 2 h everywhere; code default, executor spec and tests move from 6 to 2 (see Q3).

### Q1b. Where zero PV does enter planning (the likely cause of the user's report)

With the shipped config (`active_forecast_version: aurora`, `aurora_pv_enabled: true`, config.default.yaml:291,293) the planner does NOT call Open-Meteo itself: `get_forecast_data` -> `_get_forecast_data_aurora` (forecasts.py:84, 161) reads stored Aurora rows and calls `_get_forecast_data_async` only when `aurora_pv_enabled` is false (forecasts.py:192-193). `PVForecastError` therefore aborts a planner run only in the non-Aurora / `aurora_pv_enabled: false` configurations.

In Aurora mode the Open-Meteo baseline is fetched during inference (`run_inference`, forecasts.py:639 -> ml/forward.py:502 -> `_fetch_openmeteo_baseline_series`, forward.py:201-221). That function catches every exception, including `PVForecastError`, and returns `pd.Series(0.0)` (forward.py:216-218). The hybrid model is `baseline + bounded residual` with the residual bounded by a fraction of the baseline (forward.py:585-640, `_hybrid_pv_values`), so a zero baseline gives ~0 PV. `generate_forward_slots` then stores those rows (forward.py:674) and `store_forecasts` upserts with `COALESCE(excluded.openmeteo_pv_forecast_kwh, existing)` (store.py:463-466), so the zeros also overwrite the previously stored real baselines and `pv_forecast_kwh`. The planner reads those rows and plans with zero solar, no `PVForecastError` reaches it, while the health banner still shows "PV Forecast Failed" (forecasts.py:532-540 records it before the swallow). This matches the user's report (banner plus a zero-solar plan) and also poisons the stored baselines the fallback relies on.

Other zero-PV paths found in the same code:
- Successful fetch returning an empty estimate: `if solar_data_dict:` (forecasts.py:488) has no else, `pv_kwh_forecast` stays empty and `else 0.0` (forecasts.py:582) yields an all-zero forecast with no error.
- `solar_data_dict.get(rounded_time, 0.0)` (forecasts.py:510): slots beyond the API horizon become 0 on success.
- Stored NULL -> `or 0.0` (forecasts.py:57) is unreachable because the query excludes NULLs (store.py:811).
- `system.has_solar: false` zeroes PV on purpose (planner/pipeline.py:1421-1425); worth checking in a bug report.

Decisions taken (added to spec/tasks): (a) the Aurora inference baseline must never become zeros on failure: it must use the partial fallback, and if no usable baseline exists the inference must abort without storing (previous Aurora rows stay); (b) an empty Open-Meteo estimate is treated as a failure and goes through the fallback; (c) slots missing from a successful API response are not defaulted to 0 silently (use the same fill and flag it estimated); (d) estimated values are never persisted as `openmeteo_pv_forecast_kwh` baselines, otherwise the next run would see them as stored data, report 0 estimated and clear the banner, and ML training/pairing (`count_paired_openmeteo_pv_days`, store.py:710-790) would learn from fabricated values. Estimated slots keep their value in `pv_forecast_kwh` for the run but carry `pv_estimated: true` and a `None` baseline in the stored rows.

### Q3. User decisions

- `max_schedule_age_hours` is 2 h everywhere: change the code default (executor/config.py:340 and the `.get(..., 6)` at :1095) and the executor spec stale-schedule requirement (default 6 -> 2, MODIFIED delta). `config.default.yaml:399` already says 2 (verified, no change). Tests asserting 6 (tests/executor/test_executor_safety.py:69,296,333,355,390-393) are updated.
- No extra "give up after N hours" rule in Aurora mode: stored rows, gap fill and the banner are sufficient.
- The 50% estimated-slot threshold for the critical banner is confirmed.

### Q2. Other items resolved

- Stored coverage claim: `learning.horizon_days` defaults to 3 (config.default.yaml:244), so stored baselines end ~3 days ahead (not ~7); price slots span at most ~48 h, so the all-or-nothing miss in practice comes from fresh installs, data gaps or inference horizons longer than stored coverage.
- Banner text today: `check_forecast` ignores the recorded message for "degraded" and shows the generic "PV forecast experiencing issues" (health.py:962-970); the existing "API unreachable - using last known forecast" text is never shown. Task 2.2 must therefore read the latest entry (`last_errors[-1]`, health.py:85) context.
- Severity escalation to critical: `check_forecast` builds HealthIssue per status; critical for >50% estimated is decided in `check_forecast` from `context.estimated_slots` and `context.total_slots` (add `total_slots` to the context). Status stays "degraded".
- `system.py:316` estimated-count exposure: system.py:316 builds `ForecastHealth(pv_status, load_status, load_reason)` only; exposing the count is out of scope (banner carries it via HealthIssue message). Decision: not exposed.
- Capability name: deltas live in `open-meteo-pv-forecast` and `pv-forecast-source-indicator` (proposal corrected).
