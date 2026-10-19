## Why

Three small defects from docs/BACKLOG.md: stored forecasts report a stale `created_at`, a water-heater control-type mismatch blocks saving settings, and the planner schedules grid charging the inverter cannot deliver.

## What Changes

- Forecast upserts refresh `created_at` on overwrite (matching `store_plan`).
- Water-heater `control_type` is auto-detected from the `target_entity` domain in the settings UI and in the backend when the field is missing; a genuine explicit mismatch stays a clear, inline-visible error. The "Water tab unreachable" half was already fixed by commit 5ca78c7d (tabs no longer hidden), so no work there.
- Kepler's inverter AC limit counts grid-to-battery charging for both `dc_coupled` and `ac_coupled`.
- Item 3 builds on the archived `ev-single-phase-grid-limit` (6878b420) in the same `kepler.py` constraint loop.

## Capabilities

### New Capabilities
- `forecast-created-at`: stored forecast rows record when they were last written.

### Modified Capabilities
- `binary-water-heater-control`: control type derived from the target entity; mismatch handling (spec delta in `binary-water-heater-control/`).
- `planner`: inverter AC limit includes grid charging (spec delta in `planner/`).

## Impact

`backend/learning/store.py`, `backend/api/routers/config.py`, `executor/config.py` (shared helper only), `frontend/src/pages/settings/components/EntityArrayEditor.tsx`, `frontend/src/pages/settings/hooks/useSettingsForm.ts`, `planner/solver/kepler.py`. No schema change, no new dependencies.
