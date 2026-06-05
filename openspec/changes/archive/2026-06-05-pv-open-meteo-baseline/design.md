## Context

Diagnosed in `stabilization-review` (findings #2/#6/#7, and the agreed-direction section). Today there are two PV physics paths sharing the same open-meteo host:
- **Aurora (ML) path** — `ml/weather.py` fetches **hourly GHI** (`shortwave_radiation`) and does its **own** crude tilt transposition (`_calculate_poa_irradiance`: isotropic, fixed diffuse fraction, no temperature, ×0.85). `ml/forward.py` adds an **unbounded** ML residual (`final = physics + residual`, only night-zeroing clamps). This baseline runs low → the learned residual overshoots → ~2× for some users.
- **Library path** — `backend/core/forecasts.py` calls `OpenMeteoSolarForecast`, which requests **15-min `global_tilted_irradiance`** + temperature + real diffuse/direct and applies a proper PV model (Ross temperature derate + AC clip). Used only when `active_forecast_version != "aurora"`.

**Confirmed by data (2026-06-04, `scripts/compare_pv_paths.py`):** on the operator's 7.11 kWp config, our physics path (no ML) produced **89–124 kWh/day vs open-meteo's 36–48 (~2.5×)** — physically impossible (124 kWh ≈ 17 kWh/kWp/day; real max ~6–7). So the home-grown transposition over-produces badly. The reason the operator still sees a good forecast (MAE 0.12) is that the ML residual (`actual − physics`) learns a **large negative** correction that *cancels* the physics over-prediction; cold-start / under-trained homes haven't learned that cancellation yet, so the raw over-prediction leaks through → the ~67 kWh complaint. This change removes the root cause: a sane open-meteo baseline means the ML only ever applies a tiny nudge, so under-trained homes are never exposed. The existing `physics-based-pv-forecasting` spec already states the base SHOULD be `OpenMeteoSolarForecast`; the implementation diverged. This change realigns to that intent, makes the ML a bounded nudge, and adds a physical safety ceiling.

## Goals / Non-Goals

**Goals:**
- Make open-meteo's solar forecast the trusted PV baseline; remove the 2× overestimate on adoption.
- Reduce the ML to a **bounded** personal nudge on a good baseline; add a physical safety ceiling.
- Preserve the self-learning feature and existing users' production history; personalize via a ~10-day backfill + gradual ramp.
- Provide an outage fallback (last good fetch + warning banner) reusing existing infrastructure.
- Show the user which mode is active.

**Non-Goals:**
- No change to load forecasting, S-Index, or the planner/solver. The previously removed Aurora corrector remains inactive; PV personalization is handled by the bounded LightGBM residual model trained against the Open-Meteo baseline.
- Not deleting the home-grown calc's *code* outright if it is still referenced elsewhere — it is retired from the **baseline** role (decision in D5).
- No new external dependency (open-meteo + its library are already present).
- Not building a new banner system — reuse `record_forecast_error` → `SystemAlert`.

## Decisions

### D1 — Open-meteo `global_tilted_irradiance` PV forecast is the baseline
Use the already-integrated `OpenMeteoSolarForecast` output as `base.pv_kwh` for both inference and as the training reference. **Why over keeping home-grown POA:** open-meteo returns server-side tilted irradiance with a real diffuse/direct split + temperature derate; the home-grown isotropic/fixed-fraction transposition is the likely source of the divergence and is unnecessary duplication. Alternative considered (calibrate the home-grown calc to match) rejected: it perpetuates maintaining our own PV physics for no benefit.

### D2 — Store only successful open-meteo fetches; latest stored wins
Persist each successful open-meteo forecast per slot. The planner reads the latest stored forecast. **This store serves two purposes:** (a) outage fallback, (b) ML training history (predicted-vs-actual). Failed fetches never overwrite good data.

### D3 — ML residual is bounded; final forecast is capped
The residual is learned as `actual − openmeteo_baseline` and applied as a **bounded** nudge (cannot exceed a configured fraction of the baseline). A separate **physical ceiling** (`kWp · slot_hours · max_efficiency`, AC limit applied) caps the final value. **Why:** makes "goes crazy" structurally impossible rather than patched.

### D4 — Gradual personalization ramp by data volume
Nudge weight scales with days of the user's own data: 0 days → 100% baseline; ramps to full (bounded) nudge over a configured window. Existing users seed this with a **~28-day backfill** (open-meteo historical forecast × stored actual production), capped by `past_days` (see D7) and auto-limited by how much production history exists. **New installs have no history → backfill = 0 → they ramp forward from day 1.** **Why ramp over hard switch:** avoids a cliff where a thinly-trained model suddenly takes over; new and existing users follow the same safe curve.

### D7 — Backfill depth = ~28 days (tested), not the Historical Forecast API
The `past_days` parameter on the forecast API returns only **~28 days** of *15-minute* tilted-irradiance history (tested 2026-06-04 via `scripts/test_backfill.py`: requests for 30 and 90 both returned 28 days in ~4s). The documented 92-day `past_days` limit applies to coarser/hourly data, not the 15-min GTI we need. ~28 days is adopted as the target — it is one cheap call per array and matches the 30-day recency half-life, so deeper history would be down-weighted anyway. **Alternative considered (Historical Forecast API, back to 2021–2022) rejected for now:** extra integration for data the recency-weighting largely ignores; kept as a documented future option only.

### D5 — Retire the home-grown calc from the baseline role; fallback is last-good-fetch
The home-grown GHI→physics calc is removed as the baseline and as the outage fallback (it needs the same open-meteo host, so it never provided resilience). Outage fallback = last successful stored fetch + existing warning banner. The simplified-formula fallback in `physics-based-pv-forecasting` is replaced accordingly.

### D6 — Transparency on the Aurora Command Center
Surface forecast source + personalization progress where forecast health already lives (`pages/Aurora.tsx`, near "PV forecast quality"/training). Optional small Dashboard badge. **Why there:** that section is already about forecast health; no new page.

## Risks / Trade-offs

- **Risk:** open-meteo's historical forecast window is too short for the backfill. → **Resolved (tested):** `past_days` returns ~28 days of 15-min GTI (`scripts/test_backfill.py`, 2026-06-04) — comfortably enough for the chosen ~28-day target, in ~4s. Deeper would need the Historical Forecast API (future option). The "collect fresh, ramp from now" path is the default for new installs.
- **Risk:** one API call per array increases request volume. → **Mitigation:** 10k/day free tier is ample for residential array counts; cache per fetch window.
- **Risk:** retiring the home-grown baseline could regress a config/environment that relied on it. → **Mitigation:** keep it available as code behind the (now last-good-fetch) path during rollout; verify against the operator's MAE-0.12 config before/after.
- **Risk:** bounded nudge could under-correct a genuinely large local effect (e.g. heavy fixed shading). → **Trade-off accepted:** a capped, safe nudge is preferable to unbounded overshoot; the bound is configurable.
- **Risk:** changing the training target invalidates existing trained residual models. → **Mitigation:** retrain against the open-meteo baseline; ramp protects users during re-accumulation.

## Amendment — Independent Aurora Forecast Controls

### D8 — Aurora forecast controls are domain-specific
Expose two simple controls on the Aurora Command Center Controls card:
- `Aurora load forecasting`
- `Aurora PV forecasting`

These controls are backed by explicit config keys:
- `forecasting.aurora_load_enabled` (default `true`)
- `forecasting.aurora_pv_enabled` (default `true`)

The legacy `forecasting.active_forecast_version` selector is no longer user-facing. It may remain as an internal/coarse routing value during this change, but users should not be asked to choose between `aurora` and `baseline_7_day_avg` because that selector disables both domains at once and the name no longer describes current PV behavior.

| Aurora load forecasting | Aurora PV forecasting | Load forecast | PV forecast |
| --- | --- | --- | --- |
| On | On | Aurora ML | Open-Meteo baseline + bounded PV tuning |
| Off | On | HA load profile | Open-Meteo baseline + bounded PV tuning |
| On | Off | Aurora ML | Open-Meteo baseline only |
| Off | Off | HA load profile | Open-Meteo baseline only |

When `Aurora PV forecasting` is off, the system still fetches, stores, displays, and uses Open-Meteo PV baselines. Only the ML residual/personal tuning is disabled. When `Aurora load forecasting` is off, the system uses the existing HA load profile fallback without affecting PV behavior.

### D9 — Retire archived Forecasting UI from user-facing control path
`frontend/src/pages/archive/Forecasting.tsx` still exposes the old `active_forecast_version` selector semantics. That page should be deleted as part of this change so the user-facing model is not split between old forecast-version switching and the new domain-specific controls.

## Migration Plan

1. Start storing successful open-meteo forecasts (no behavior change yet).
2. Switch the baseline (`active`/aurora path) to read the open-meteo forecast; apply safety ceiling. → 2× removed immediately.
3. Backfill ~10 days for existing users; enable the bounded residual + ramp.
4. Add the source indicator and independent Aurora load/PV forecast controls.
5. Retire the home-grown baseline path; outage fallback = last good fetch + banner.
6. Remove the archived Forecasting page that exposed the legacy forecast-version selector.
- **Rollback:** revert the baseline switch (step 2) to restore prior behavior; stored forecasts are additive and harmless.

## Open Questions

- ~~Exact open-meteo historical-forecast depth available for backfill.~~ **Resolved (tested):** `past_days` yields ~28 days of 15-min GTI (not 92 — that's for hourly). Target = ~28 days. Deeper would require the Historical Forecast API (predicted values, back to 2021–2022; not the ERA5 reanalysis) — future option only.
- Exact numeric bounds: residual cap fraction, safety-ceiling efficiency, and ramp window length (defaults to be set in tasks, tunable in config).
- ~~Where should the ML disable control live?~~ **Resolved:** Aurora Command Center Controls card, as two domain-specific toggles for load and PV.

## References
- `openspec/changes/stabilization-review/findings.md` — diagnosis (#2/#6/#7) and agreed direction.
- `specs/physics-based-pv-forecasting/spec.md` (modified), `specs/pv-personalization-ramp/spec.md`, `specs/pv-forecast-source-indicator/spec.md`.
