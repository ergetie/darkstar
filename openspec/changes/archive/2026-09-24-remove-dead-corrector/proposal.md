## Why

The corrector was removed in `fad904e3` (2026-03-14), but its UI and API were left in place. The Model Training card still shows a "Corrector: Ready" tile whose age comes from leftover `*_error.lgb` files (195 days old on prod). A correction-history API field and an unused chart component also remain. On prod, no correction has been stored since 2026-03-11.

## What Changes

- Remove the Corrector tile from `ModelTrainingCard` and the `*error*` file detection behind it.
- Remove the unused `CorrectionHistoryChart` component and the `AuroraHistoryDay` type.
- Remove `_fetch_correction_history` and the `correction_history` field from the forecast API response. **BREAKING** (API field removed; no frontend consumer).
- Remove the dead `correction` field from `AuroraHorizonSlot` and the example data in `ChartExamples.tsx`.
- Update the stale "+ corrector" docstring in `ml/forward.py`.
- Add an Alembic migration that drops `pv_correction_kwh`, `load_correction_kwh` and `correction_source` from `slot_forecasts`, and remove them from the ORM model. **BREAKING** (schema). It runs automatically on update and has a working downgrade.
- Leftover `*_error.lgb` files on user installs are left alone; users can delete them.

## Capabilities

### New Capabilities

### Modified Capabilities
- `aurora-corrector`: add a requirement that no corrector status or correction history is surfaced in the API or UI.

## Impact

- Frontend: `components/aurora/ModelTrainingCard.tsx`, `components/CorrectionHistoryChart.tsx` (deleted), `lib/types.ts`, `pages/ChartExamples.tsx`.
- Backend: `backend/api/routers/forecast.py`, `backend/learning/models.py`, `backend/learning/store.py`, `ml/forward.py` (docstring only).
- Database: new migration under `alembic/versions/` (down_revision `b7c9d1e2f3a4`). The old correction values (all unused, all older than 2026-03-11) are discarded.
