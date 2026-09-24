## 1. Frontend

- [x] 1.1 `ModelTrainingCard.tsx`: remove the Corrector tile and `correctorModel`; select the main model only from `*model*` filenames; make the Main Models tile full width
- [x] 1.2 Delete `components/CorrectionHistoryChart.tsx`
- [x] 1.3 `lib/types.ts`: remove `AuroraHistoryDay` and the `correction` field of `AuroraHorizonSlot`; fix `ChartExamples.tsx` example data
- [x] 1.4 Remove any `correction_history` typing in `lib/api.ts`/types, if present

## 2. Backend

- [x] 2.1 `backend/api/routers/forecast.py`: delete `_fetch_correction_history`, its call, and the `correction_history` response key; drop now-unused imports
- [x] 2.2 `ml/forward.py`: remove "+ corrector" from the module docstring

## 3. Database

- [x] 3.1 Remove `pv_correction_kwh`, `load_correction_kwh` and `correction_source` from `SlotForecast` in `backend/learning/models.py`
- [x] 3.2 `backend/learning/store.py`: drop the three columns from the `get_forecasts_range` select; delete the "backward compatibility" comment
- [x] 3.3 Add an Alembic migration (down_revision `b7c9d1e2f3a4`): inspect-guarded `batch_alter_table` drop; the downgrade re-adds the columns with the original types and server defaults
- [x] 3.4 Migration test: build a DB at `b7c9d1e2f3a4` with seeded rows → upgrade → assert the columns are gone and the rows and other values are intact; run upgrade twice (idempotent); downgrade → the columns come back
- [x] 3.5 Dry run against a copy of the prod DB (`ssh darkstar`, copy `planner_learning.db` read-only, migrate it locally), then check the row count and `PRAGMA integrity_check`
- [x] 3.6 `scripts/profile_db.py`: remove the NULL-check and `_init_schema` UPDATE profiling of the dropped columns (would fail after the migration)

## 4. Verify

- [x] 4.1 `rg -i "corrector|correction_history|CorrectionHistory"` finds no live code refs (specs/docs excepted)
- [x] 4.2 Run `./scripts/lint.sh` (includes the frontend typecheck and tests); all green
