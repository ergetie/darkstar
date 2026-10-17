## Context

`_pv_tuning_config` in `ml/forward.py` reads `pv_residual_bound_fraction` with `float(x.get(key, 0.25) or 0.25)`, so 0 becomes 0.25. `_hybrid_pv_values` clamps the residual to +/- baseline * fraction. `ml_residual_{q}` is stored only in memory (bounded). `ml/weather.py` has the same `or` pattern for tilt/azimuth. Reflex only tunes `pv_confidence_percent` and similar keys (verified by grep of `backend/learning/reflex.py`). The settings UI has no control for this key.

## Goals / Non-Goals

**Goals:** better default PV accuracy; honour configured zeros; enable exact future evaluation of limits; safe upgrade for existing users.
**Non-Goals:** asymmetric bounds (no benefit in replay), retraining, a new UI control, changing the personalization ramp.

## Decisions

1. **Default 1.0, symmetric.** Replay: MAE -21%, bias +20% to +7.4%. The ceiling, floor, sun clamp and `pv_confidence_percent` remain as other guards.
2. **Zero is meaningful.** 0 yields max_residual 0, so the forecast equals the baseline: a valid "disable the nudge" setting. New helper parses: None or missing -> default; non-finite or negative -> default (with a warning); else the value. Same approach for ceiling_efficiency and ramp_days is out of scope (0 is not meaningful there; ramp already uses max(1.0, ...)).
3. **Migration `_migrate_pv_residual_bound`**, called in `_migrate_config` pre-merge next to `_migrate_target_margin`. Compare with `float(v) == 0.25` (guard bool and non-numeric: leave untouched). Set 1.0, return `(config, True)`. Known limitation: a user who deliberately set 0.25 is indistinguishable from the old default and also moves to 1.0; they can set another value (e.g. 0.26) or 0 afterwards. Accepted by the user decision.
4. **Raw residual storage.** New nullable `Float` column `pv_ml_residual_raw_kwh` on `slot_forecasts` (p50 raw model output, unbounded and unweighted, so the bound and weight can be re-applied exactly). `ml/forward.py` adds it to each slot item from `raw_pred` for q=p50 (None in baseline-only mode); `store_forecasts` and the upsert in `backend/learning/store.py` persist it; `models.py` gets the mapped column. The stored value is before bounding, weighting and the 3-slot centred smoothing; an exact re-evaluation re-applies all three plus the existing clamps (sun-up, radiation, floor, ceiling) in the same order as `ml/forward.py`.
5. **DB schema change, approved by the user on 2026-10-17.** New Alembic revision with `down_revision = "b7e2c4a9f1d3"` (current head), `op.add_column` nullable (batch mode for SQLite), downgrade drops it. Approval was given on 2026-10-17.
6. **Tilt/azimuth.** Replace `float(x or default)` with a helper returning the default only when the value is None (or missing).

## Risks / Trade-offs

- Replay used archive weather and in-sample models, so live gains may be smaller. Mitigation: raw residual storage allows re-evaluation; users can set a lower bound.
- A looser bound lets a bad model move forecasts further. Mitigation: existing ceiling/floor/ramp guards and quantile ordering.
- Schema change touches a hot table. Mitigation: nullable add-column, no backfill.
- Users who set exactly 0.25 on purpose get 1.0 (see decision 3).

## Migration Plan

Alembic upgrade adds the column; config migration runs on startup. Rollback: downgrade drops the column; users restore 0.25 manually.

## Open Questions

None blocking. Schema approval is required before applying the DB task group.

## Rollout

The config migration runs on every startup path (`scripts/docker-entrypoint.sh`, `darkstar/run.sh`, `darkstar-dev/run.sh`), so add-on and Docker users get it on their next update. The tilt/azimuth fix only affects the physics estimate (`calculate_physics_pv`, used by the Aurora API/dashboard and the fallback path); the ML feature `physics_forecast_kwh` is the Open-Meteo baseline, so no retraining is needed.
