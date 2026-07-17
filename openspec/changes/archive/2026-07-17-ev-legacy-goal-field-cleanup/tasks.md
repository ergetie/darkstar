# Tasks: ev-legacy-goal-field-cleanup

## 1. Backend: unblock settings saves

- [x] 1.1 Delete the per-charger `departure_time` validation block in `backend/api/routers/config.py` (~lines 662-673, the `dev_departure` regex check)
- [x] 1.2 Delete the root `ev_departure_time` validation block in `backend/api/routers/config.py` (~lines 699-710, the "REV K25 Phase 2" check); remove the now-unused `re` import only if nothing else in the file uses it
- [x] 1.3 Add a regression test: `validate_config()` (or the settings save endpoint) returns no error/warning for a charger entry with `departure_time: 1200` and with a `penalty_levels` list present (per-device-ev-scheduling scenario "Malformed legacy goal value does not block settings save")

## 2. Backend: config migration strips legacy goal fields

- [x] 2.1 Make the deprecated goal field list shared: move/expose `_DEPRECATED_EV_GOAL_FIELDS` from `executor/config.py` so `backend/config_migration.py` imports the same tuple (pick import direction that avoids a backend→executor cycle; a shared constants module is acceptable)
- [x] 2.2 Add `_remove_ev_goal_fields()` to `backend/config_migration.py`, modeled on `_remove_energy_sensor_fields()`: delete every deprecated goal field key from each `ev_chargers[]` item, log each removal, return `(config, changed)`
- [x] 2.3 Register `_remove_ev_goal_fields()` in the migration sequence in `migrate_config()` (after `_migrate_ev_charger_fields`, before deprecated-key removal is fine — order only matters in that it must run every migration pass)
- [x] 2.4 In `_migrate_ev_charger_fields()`, delete the `ev_departure_time -> departure_time` copy block (lines ~282-289); leave `ev_departure_time` in `DEPRECATED_KEYS` so the root key is still swept
- [x] 2.5 Add migration tests: (a) charger with `departure_time: 1200` and `penalty_levels: [...]` → both keys gone after migration, change flag set; (b) clean charger entry → no change flag from this step (idempotency); (c) root `ev_departure_time` present → removed from root and NOT copied into any charger
- [x] 2.6 Update or remove existing migration tests that assert the old `ev_departure_time -> ev_chargers[0].departure_time` copy behavior (search `tests/` for `ev_departure_time`)

## 3. Backend/planner: delete dead deadline code

- [x] 3.1 Delete `calculate_ev_deadline()` from `planner/pipeline.py` and any now-unused imports it leaves behind
- [x] 3.2 Delete `tests/ev/test_ev_departure_deadline.py` and `tests/ev/test_ev_departure_integration.py`
- [x] 3.3 Repo-wide grep for `calculate_ev_deadline` and `departure_time` in `*.py`; confirm remaining hits are only the shared deprecated-field list, migration strip step, and their tests

## 4. Frontend: remove legacy fields and dead penalty UI

- [x] 4.1 In `frontend/src/pages/settings/components/EntityArrayEditor.tsx`: remove `departure_time` and `penalty_levels` from the `EVChargerEntity` interface and from `createDefaultEVCharger()`
- [x] 4.2 In `EntityArrayEditor.tsx`: delete the entire inline "Penalty Levels" section (the `bg-surface2/30` block with Add Level / Max SoC / Penalty rows and its help `<details>`)
- [x] 4.3 Delete `frontend/src/pages/settings/components/PenaltyLevelsEditor.tsx` and its `case 'penalty_levels'` branch in `SettingsField.tsx`
- [x] 4.4 Remove the `penalty_levels` field type from `frontend/src/pages/settings/types.ts` and its branches in `frontend/src/pages/settings/utils.ts`
- [x] 4.5 Remove `penalty_levels` from the EV charger config type in `frontend/src/lib/api.ts`
- [x] 4.6 Update any frontend tests referencing `departure_time` or `penalty_levels` (search `frontend/src` for both strings); run `pnpm test` and typecheck to confirm nothing else consumed them

## 5. Specs and docs

- [x] 5.1 Verify the delta specs in this change validate: `openspec validate ev-legacy-goal-field-cleanup` (main specs update happens at archive/sync time)
- [x] 5.2 Check `docs/` and `config.default.yaml` for mentions of `departure_time` / `penalty_levels` as live EV config fields; fix any found (template verified clean at proposal time, re-verify)

## 6. Verify end-to-end

- [x] 6.1 Run the full backend test suite (`pytest`) and frontend tests/typecheck; all green
- [x] 6.2 Manual reproduction check: start the app with a config containing `ev_chargers[0].departure_time: 1200` and a `penalty_levels` list → startup migration rewrites config (backup created, keys gone), EV settings page saves successfully, executor logs no deprecation warning after migration
