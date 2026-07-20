# Tasks: price-forecast-anchoring

## 1. Inference — pass the database session

- [x] 1.1 In `ml/price_forecast.py:generate_price_forecasts`, open a SQLAlchemy session against `db_path` (same `create_engine(f"sqlite:///{db_path}")` + `sessionmaker` pattern as `_persist_forecasts` in the same file) BEFORE the `for days_ahead in range(1, 8)` loop, and close it in a `finally` block after the loop
- [x] 1.2 Pass that session as `db_session=` to the `build_price_features_batch(...)` call (~lines 181-186); make NO changes to `ml/price_features.py` — it already accepts and uses `db_session`

## 2. Training — issue-time knowability mask

- [x] 2.1 In `ml/price_train.py:_add_price_lag_features`, after computing each row's lags, apply the mask using the row's `issue_timestamp` (already parsed to tz-aware datetime at line ~174): set `price_lag_1d` to NaN unless `slot_start − timedelta(days=1) < issue_timestamp`; set `price_lag_7d` to NaN unless `slot_start − timedelta(days=7) < issue_timestamp`; set `price_lag_24h_avg` to NaN unless `slot_start − timedelta(days=1) < issue_timestamp` (whole-window rule — no partial-window averages)
- [x] 2.2 Skip the DB lookups entirely for rows the mask would NaN anyway (cheap guard before querying, not just masking after) — keeps training dataset build time from growing

## 3. Tests

- [x] 3.1 New test for inference wiring: with a seeded in-memory/tmp `slot_observations` row at slot−1d, `build_price_features_batch` called the way `generate_price_forecasts` now calls it returns a populated `price_lag_1d` for that slot, and NaN for a slot whose lag source has no observation row (verifies the ISO-string/timezone match works end-to-end with tz-aware Europe/Stockholm slots)
- [x] 3.2 New test for the training mask: build a small training df with controlled `issue_timestamp`/`slot_start` pairs — a `days_ahead=1` row with lag source before issue keeps its `price_lag_1d`; a `days_ahead=5` row whose lag source is after issue gets NaN despite the observation existing in the DB; `price_lag_7d` behaves per its own rule on both
- [x] 3.3 Run the existing ML test suites touching these files (`tests/` price forecast/training tests) — no regressions

## 4. Retrain + production verification

- [x] 4.1 Deploy, then trigger a price model retrain via the existing training entry point (or wait for the next scheduled Aurora run — user's call at implementation time); confirm the three model files are rewritten
- [x] 4.2 Trigger forecast generation; query `price_forecasts` on prod (read-only python via `ssh darkstar`, per `reference_prod_server` memory) and confirm D+1 rows were built with populated lags (spot-check: forecast level near the boundary tracks the last known actuals)
- [x] 4.3 Acceptance check — midnight boundary: compare the last ~4 actual slots of today (`slot_observations.export_price_sek_kwh`) against the first ~4 D+1 forecast slots (`spot_p50`); the step at 00:00 SHALL be in line with typical slot-to-slot variation, no systematic level jump. Record before/after numbers in the change's verification notes
- [x] 4.4 If (and only if) 4.3 still shows a systematic jump: STOP — do not implement blending here; report findings to the user and propose a separate boundary-blend change (not triggered — acceptance passed, see design.md Verification Notes)
- [x] 4.5 Watch `d1_mae` (existing accuracy KPI) over the following days for regression; note the baseline value at deploy time in the verification notes (baseline recorded: 0.2894; ongoing monitoring is outside this session's scope)
