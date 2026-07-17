# Proposal: ev-legacy-goal-field-cleanup

## Why

A beta tester cannot save anything on the EV settings page: their config still contains a legacy `departure_time: 1200` value (from before the goal-based EV charging model), and `validate_config()` hard-errors on it — even though the current `per-device-ev-scheduling` spec requires that legacy goal fields in config be *ignored with a deprecation warning* and that malformed values *never* block config loading. The settings UI no longer exposes the field, so the user has no way to fix the error from the UI. Several other leftovers from the pre-goal-based model (dead `calculate_ev_deadline` code, a migration that actively plants `departure_time`, a Penalty Levels editor for a field nothing reads) compound the confusion.

## What Changes

- Remove the save-blocking validation for per-charger `departure_time` and root `ev_departure_time` in `backend/api/routers/config.py`.
- Config migration strips deprecated EV goal fields (`departure_time`, `penalty_levels`, `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, `keep_on_after_target`) from `ev_chargers[]` entries, following the existing `_remove_energy_sensor_fields` pattern. The migration's existing atomic-write-with-backup covers rollback; no extra backup added.
- Config migration stops planting `departure_time`: `_migrate_ev_charger_fields` no longer copies root `ev_departure_time` into `ev_chargers[0].departure_time` (the root key is still swept via `DEPRECATED_KEYS`).
- **BREAKING (config)**: legacy `departure_time` / `penalty_levels` values in `config.yaml` are deleted on migration rather than preserved. They have had no runtime effect since the goal-based model landed (`ev-goal-charging-fixes`, 2026-07-10); goals live in `data/ev_multi_day_state.json` via the dashboard.
- Delete dead code: `calculate_ev_deadline()` in `planner/pipeline.py` and its test files (`tests/ev/test_ev_departure_deadline.py`, `tests/ev/test_ev_departure_integration.py`).
- Frontend: remove `departure_time` and the inline Penalty Levels editor from `EntityArrayEditor.tsx` and the `EVChargerEntity` type; delete the unused `PenaltyLevelsEditor.tsx` component and the dead `penalty_levels` field-type plumbing in `SettingsField.tsx`, `types.ts`, `utils.ts`, and `lib/api.ts`.
- Update stale spec sections that still mandate the old behavior (`config-migration`, `planner`).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `config-migration`: no longer migrates root `ev_departure_time` into `ev_chargers[0].departure_time`; instead strips deprecated EV goal fields from `ev_chargers[]` entries.
- `planner`: drop the per-charger `ev_deadline`-from-`departure_time` requirement (superseded by goal-based `ready_by` deadlines from the state file).
- `per-device-ev-scheduling`: config validation must not reject (block saves on) deprecated goal fields — strengthens the existing "malformed values SHALL NOT crash config loading" requirement to cover the save/validate path.

## Impact

- `backend/api/routers/config.py` — remove two validation blocks.
- `backend/config_migration.py` — new strip step, trimmed `_migrate_ev_charger_fields`.
- `planner/pipeline.py` — remove dead function.
- `tests/ev/` — remove two dead test files; add migration + validation regression tests.
- `frontend/src/pages/settings/` (`EntityArrayEditor.tsx`, `SettingsField.tsx`, `types.ts`, `utils.ts`, `components/PenaltyLevelsEditor.tsx`), `frontend/src/lib/api.ts`.
- `openspec/specs/config-migration/spec.md`, `openspec/specs/planner/spec.md`, `openspec/specs/per-device-ev-scheduling/spec.md`.
- User-visible: beta testers with stale configs can save EV settings again after upgrade; the misleading Penalty Levels UI disappears.
