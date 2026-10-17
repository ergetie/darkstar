## 1. PV residual bound default and zero handling

- [x] 1.1 Change `pv_residual_bound_fraction` to 1.0 in `config.default.yaml` (~L296) and update its comment
- [x] 1.2 In `ml/forward.py` `_pv_tuning_config`, add a parser: missing/None -> 1.0, non-finite or negative -> 1.0 with warning, valid 0 honoured
- [x] 1.3 Tests (`tests/ml/`): default 1.0 when missing, 0 honoured (forecast equals baseline), 0.5 kept, invalid -> 1.0; update `tests/ml/test_pv_openmeteo_backfill.py` fixture if affected

## 2. Config migration of old default

- [x] 2.1 Add `_migrate_pv_residual_bound` in `backend/config_migration.py` (exactly 0.25 -> 1.0; others, including 0 and non-numeric, untouched; missing key untouched) and call it pre-merge after `_migrate_target_margin`, setting `pre_merge_changes`
- [x] 2.2 Tests: 0.25 replaced, 0.4/0/2.0 kept, missing key gets 1.0 via template merge, second run idempotent with no file rewrite, bool/string values untouched
- [x] 2.3 Add a test asserting Reflex does not touch `forecasting.pv_residual_bound_fraction`

## 3. Raw residual storage (DB schema change, approved by the user 2026-10-17)

- [x] 3.1 Obtain explicit user approval for the `slot_forecasts` schema change (approved 2026-10-17)
- [x] 3.2 Add nullable `pv_ml_residual_raw_kwh` to `SlotForecast` in `backend/learning/models.py`
- [x] 3.3 Add Alembic revision (down_revision `b7e2c4a9f1d3`) adding/dropping the column
- [x] 3.4 In `ml/forward.py` add raw p50 residual to each slot item (None in baseline-only mode); persist in `backend/learning/store.py`
- [x] 3.5 Tests: re-applying bound, weight and the 3-slot smoothing to the stored raw residual reproduces stored `pv_forecast_kwh` (p50) for a fixture horizon; migration upgrade/downgrade keeps rows (pattern of `tests/test_migration_*.py`), hybrid stores raw 0.4 while forecast uses the bounded value, baseline-only stores NULL, forecast values unchanged

## 4. Panel orientation zero handling

- [x] 4.1 In `ml/weather.py` (~L215/L218) honour tilt 0 and azimuth 0; default 30/180 only when missing/None
- [x] 4.2 Tests: tilt 0 flat array, azimuth 0, missing and None use defaults

## 5. Settings UI check

- [x] 5.1 Grep `frontend/src` for `pv_residual_bound_fraction`; confirm there is no settings field (only the type in `frontend/src/lib/api.ts`); if one exists, update its help and range (0 to 2, default 1.0); add/adjust a frontend test if changed

## 6. Final checks

- [x] 6.1 Run `./scripts/lint.sh` and fix all failures
