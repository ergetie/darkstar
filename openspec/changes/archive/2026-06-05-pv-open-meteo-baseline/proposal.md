## Why

PV forecasting overestimates ~2× for some users (open-meteo's own forecast ~29 kWh, Darkstar ~67 kWh, actual ~34 kWh). Diagnosis in `stabilization-review` (findings #2/#6/#7) showed the Aurora baseline does its **own** GHI→tilt transposition (crude isotropic, fixed diffuse fraction, no temperature derating, ×0.85) which runs systematically **low** — so the ML residual (`actual − physics`) learns a large positive correction that overshoots, especially for cold-start or unusual-geometry homes. Notably the existing `physics-based-pv-forecasting` spec already states the base SHOULD be `OpenMeteoSolarForecast`, but the implementation diverged to the home-grown calc. This change realigns to that intent: open-meteo's solar forecast becomes the trusted baseline and ML becomes a small, bounded personal nudge.

## What Changes

- **Open-meteo solar forecast becomes the PV baseline.** It already returns plane-of-array (tilted) irradiance, real diffuse/direct split, and temperature derating; it is already integrated (`backend/core/forecasts.py`) and handles multiple arrays. Free tier (10k calls/day) is ample even with one call per array.
- **Retire the home-grown GHI→physics calc as the baseline.** It hits the *same* open-meteo host, so it was never a valid outage backup; its training-baseline role is replaced by stored open-meteo forecasts.
- **ML becomes a bounded personal nudge.** The residual is learned against the open-meteo baseline and is **capped** so it can never double or flip the forecast. A **safety ceiling** prevents physically impossible output.
- **Gradual personalization ramp.** New homes run on 100% open-meteo; the nudge fades in weighted by how many days of the user's own data exist. **Existing** users get a **~28-day backfill** (open-meteo history × stored actual production) so tuning starts quickly without discarding their production history. **New installs have no production history, so backfill auto-shrinks to 0 and they simply ramp forward** — backfill is purely an existing-user accelerator.
- **Fallback = last successful fetch.** Only successful open-meteo fetches are stored; the planner always uses the latest stored forecast. On an API outage it keeps using the last good fetch and raises a warning via the **existing** `record_forecast_error` → `SystemAlert` banner path. This same stored history feeds ML training (predicted-vs-actual) — one mechanism, two uses.
- **Transparency indicator.** The Aurora Command Center shows forecast source ("Open-meteo baseline" → "+ personal tuning (active)") with personalization progress; optional small badge on the Dashboard forecast.
- **Independent Aurora forecast controls.** The Aurora Command Center exposes two simple controls: "Aurora load forecasting" and "Aurora PV forecasting". Turning PV forecasting off disables only the PV ML residual/personal tuning and keeps Open-Meteo as the PV baseline. Turning load forecasting off disables only Aurora load ML and falls back to the HA load profile. The legacy `active_forecast_version` selector is no longer user-facing.

## Capabilities

### New Capabilities
- `pv-personalization-ramp`: Bounded ML nudge on top of the open-meteo baseline, with a data-volume-weighted ramp (cold-start = pure baseline), a ~10-day backfill for existing users, and a physical safety ceiling on the final forecast.
- `pv-forecast-source-indicator`: User-facing indication of which forecast mode is active (baseline vs personalized) and personalization progress, on the Aurora Command Center (and optional Dashboard badge).
- `aurora-forecast-controls`: User-facing controls for independently enabling/disabling Aurora load forecasting and Aurora PV forecasting without changing the other domain.

### Modified Capabilities
- `physics-based-pv-forecasting`: The base changes from the home-grown POA calc to open-meteo's tilted-irradiance forecast; the ML residual is learned against (and stored relative to) that baseline; the retroactive home-grown physics step and the simplified-formula fallback are replaced by stored open-meteo forecasts and a last-good-fetch fallback.

## Impact

- **Code:** `ml/forward.py`, `ml/train.py`, `ml/weather.py` (retire home-grown baseline path), `backend/core/forecasts.py` (open-meteo baseline + store successful fetches + independent load/PV forecast routing), `backend/learning/store.py` (persist open-meteo forecasts; backfill), `backend/health.py` (already has `record_forecast_error`), `frontend` Aurora page + Dashboard (source indicator and forecast controls), remove archived Forecasting UI.
- **Data:** new/extended storage for open-meteo forecasts per slot (feeds both fallback and training). Existing `slot_observations` (actual production) preserved.
- **Behavior:** the 2× overestimate is removed immediately on adoption (baseline switch); personalization re-attaches via backfill/ramp; users can disable Aurora PV tuning independently from Aurora load forecasting.
- **External:** open-meteo `/v1/forecast` (tilted irradiance), 1 call per array; free tier 10k/day.
- **Relations:** addresses `stabilization-review` findings #2/#6/#7; interacts with `aurora-corrector`, `recency-weighted-training`, `open-meteo-pv-forecast`.
- **Backfill source (tested 2026-06-04, `scripts/test_backfill.py`):** the cheap `past_days` method yields **~28 days** of 15-min tilted-irradiance history (NOT 92 — that limit is for hourly data), one call per array, ~4s. ~28 days is the chosen target since it matches the 30-day recency half-life. Deeper backfill would require the **Historical Forecast API** (archived predictions back to 2021–2022; not the ERA5 reanalysis) — noted as a future option, not used now.
