# Tasks — pv-open-meteo-baseline

> Order matters: store first (harmless), then switch baseline (removes 2×), then bounded residual + ramp, then UI, then retire home-grown. Each numbered group is independently verifiable. Numeric defaults (bound fraction, ceiling efficiency, ramp window) are set here and exposed in config.

## 1. Store open-meteo forecasts (no behavior change yet)

- [x] 1.1 On every successful open-meteo solar fetch, persist the per-slot forecast (store only on success; never overwrite good data with a failed/empty fetch)
- [x] 1.2 Extend the forecast store/schema to hold the open-meteo baseline per slot alongside existing fields (`backend/learning/store.py`, migration if needed — ask before schema change per AGENTS.md)
- [x] 1.3 Confirm multi-array fetch works and is summed correctly (one call per array); add a test

## 2. Switch the PV baseline to open-meteo (removes the 2×)

- [x] 2.1 Make the aurora/inference path read the open-meteo baseline (`global_tilted_irradiance` PV) instead of the home-grown POA calc (`ml/forward.py`, `backend/core/forecasts.py`)
- [x] 2.2 Apply the physical safety ceiling to the final forecast (`kWp · slot_hours · max_efficiency`, inverter AC limit applied)
- [x] 2.3 Verify against the operator's MAE-0.12 config that baseline-only output is sane (regression guard)
- [x] 2.4 Update API response so `base.pv_kwh` = open-meteo baseline; keep `final.pv_kwh` authoritative + backward compatible

## 3. Bounded ML nudge + retarget training

- [x] 3.1 Change PV training target to `actual − stored_openmeteo_baseline` (`ml/train.py`)
- [x] 3.2 Apply the residual at inference as a bounded nudge (cannot exceed configured fraction of baseline) (`ml/forward.py`)
- [x] 3.3 Add config keys: residual bound fraction, ceiling efficiency, ramp window (with sensible defaults)
- [x] 3.4 Retrain/validate residual models against the new baseline; confirm no overshoot on test data

## 4. Personalization ramp + backfill + cold-start

- [x] 4.1 Implement the data-volume ramp: 0 days → baseline only; scale residual weight to full over the configured window
- [x] 4.2 Implement ~28-day backfill for actual-production slots missing an Open-Meteo baseline (open-meteo historical forecast × stored actual production) to seed training + the ramp day-count. Source: `past_days` (yields ~28 days of 15-min GTI, ~4s, one call/array — verified by `scripts/test_backfill.py`). Skip the API call when no baseline slots are missing; new installs (no history) skip backfill. Historical Forecast API (deeper, 2021+) is a future option only — do NOT use the ERA5 reanalysis archive
- [x] 4.3 Handle backfill-unavailable gracefully (baseline-only, accumulate from now, log it)
- [x] 4.4 Confirm existing `slot_observations` production data is preserved (no destructive migration)
- [x] 4.5 Tests: cold-start = pure baseline; partial ramp scales; full ramp respects the bound

## 5. Outage fallback (last good fetch + existing banner)

- [x] 5.1 On fetch failure, use the latest stored open-meteo forecast for the planning window
- [x] 5.2 Raise `record_forecast_error` so `SystemAlert` shows "API unreachable — using last known forecast" (warning)
- [x] 5.3 Escalate to the existing critical forecast-failure issue when the stored forecast no longer covers the window
- [x] 5.4 Tests: outage → last-good-fetch used + warning surfaced; exhausted → critical

## 6. Transparency indicator (UI)

- [x] 6.1 Aurora Command Center (`pages/Aurora.tsx`): show source ("Open-Meteo baseline" → "+ personal tuning (active)") near "PV forecast quality"/training
- [x] 6.2 Show personalization progress (days collected vs ramp window / "personalizing in ~N days")
- [x] 6.3 (Optional) compact Dashboard forecast badge, consistent with the Aurora indicator

## 6A. Independent Aurora forecast controls (amendment)

- [x] 6A.1 Add config defaults for `forecasting.aurora_load_enabled: true` and `forecasting.aurora_pv_enabled: true`
- [x] 6A.2 Replace any broad user-facing `active_forecast_version` / "Aurora ML forecast" control with two simple Aurora Controls card toggles: "Aurora load forecasting" and "Aurora PV forecasting"
- [x] 6A.3 Remove `active_forecast_version` from user-facing UI; keep it internal/legacy only if still needed for routing
- [x] 6A.4 Route load and PV independently in backend forecast assembly: load-off uses HA load profile, PV-off uses Open-Meteo baseline only
- [x] 6A.5 Ensure PV-off mode still fetches/stores/returns `openmeteo_pv_forecast_kwh` and does not apply the bounded ML residual
- [x] 6A.6 Ensure load-off mode does not disable Aurora PV behavior when Aurora PV forecasting remains on
- [x] 6A.7 Update PV source/status display for PV tuning disabled vs baseline-only ramp vs personalized modes
- [x] 6A.8 Add backend tests for all four load/PV toggle combinations
- [x] 6A.9 Add frontend tests for both toggles and PV source/status display states
- [x] 6A.10 Delete `frontend/src/pages/archive/Forecasting.tsx` and remove any dead frontend references/types left by that deletion

## 7. Retire home-grown baseline + close out

- [x] 7.1 Remove the home-grown GHI→POA calc from the baseline/fallback role (keep code available during rollout per design D5; remove once 2.x + 5.x verified)
- [x] 7.2 Replace the simplified-formula fallback referenced in `physics-based-pv-forecasting` with the last-good-fetch behavior
- [x] 7.3 Run `./scripts/lint.sh` + full test suite; confirm baseline of 1051+ tests still passes
- [x] 7.4 Update docs (`docs/ARCHITECTURE.md` Aurora Vision section) to reflect open-meteo baseline + bounded nudge
- [x] 7.5 Update `stabilization-review/findings.md` #2/#6/#7 status to resolved when shipped
