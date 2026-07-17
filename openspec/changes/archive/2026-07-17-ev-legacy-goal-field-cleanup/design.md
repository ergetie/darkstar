# Design: ev-legacy-goal-field-cleanup

## Context

The goal-based EV charging model (`ev-goal-charging-fixes`, commit `d9137016`, 2026-07-10) moved all charging-goal fields out of `config.yaml` into `data/ev_multi_day_state.json`, owned by the dashboard card / EV API / HA sync. The executor already treats these fields as deprecated (`executor/config.py:_DEPRECATED_EV_GOAL_FIELDS` — warn once, ignore). But four subsystems were never updated:

1. `validate_config()` (`backend/api/routers/config.py:662-673`, `699-710`) still hard-errors on malformed `departure_time` / `ev_departure_time`, blocking **all** settings saves for users whose config carries a stale value the UI can no longer edit.
2. `_migrate_ev_charger_fields()` (`backend/config_migration.py:282-289`) still copies root `ev_departure_time` into `ev_chargers[0].departure_time`, actively planting the deprecated field.
3. `calculate_ev_deadline()` (`planner/pipeline.py:655`) has no runtime callers — only its own tests.
4. The frontend still round-trips `departure_time` and renders a full Penalty Levels editor (inline in `EntityArrayEditor.tsx`) for a field nothing consumes; `PenaltyLevelsEditor.tsx` and the `penalty_levels` field type in the generic settings framework are entirely unreferenced by any field definition.

## Goals / Non-Goals

**Goals:**
- A config carrying any legacy EV goal field — valid or malformed — never blocks a settings save.
- Migration removes the legacy fields from `config.yaml` once, permanently (relying on the migration system's existing atomic-write-with-backup for rollback safety).
- Dead code and misleading UI are deleted.
- Specs match reality.

**Non-Goals:**
- No changes to the goal-based charging model itself (`ready_by`, `target_soc_percent`, state file, dashboard card, EV API).
- No new backup mechanism — `write_config_atomic` with persistent backup dir already covers it (verified: `config_migration.py` "atomic write with backup", `_get_persistent_backup_dir`).
- No downgrade path: users reverting to a pre-goal-based version after migration lose old `departure_time`/`penalty_levels` values (accepted; recoverable from the automatic migration backups).

## Decisions

**D1 — Strip deprecated goal fields in migration, mirroring `_remove_energy_sensor_fields`.**
New step `_remove_ev_goal_fields()` iterates `ev_chargers[]` and deletes every key in the deprecated set (`departure_time`, `penalty_levels`, `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, `keep_on_after_target`), logging each removal. Rationale: the executor's warn-and-ignore keeps working for configs that skip migration (e.g. read-only mounts), but migrated configs are clean so the warning noise and stale data disappear. Alternative considered: only warn, never strip — rejected, keeps the trap in place forever and the user explicitly chose stripping.

**D2 — The deprecated-field list is defined once in the migration module and imported by the executor** (or vice versa) rather than duplicated. `executor/config.py` already owns `_DEPRECATED_EV_GOAL_FIELDS`; the migration should reuse that tuple (import from executor, or move to a shared location if the import direction is awkward). Rationale: two hand-maintained copies will drift.

**D3 — Delete the validators, don't downgrade them to warnings.**
`validate_config()` simply stops checking `departure_time` / `ev_departure_time`. Rationale: after migration the fields don't exist; a warning about a field the UI can't show is noise. The root `ev_departure_time` sweep via `DEPRECATED_KEYS` already removes the other legacy key.

**D4 — `_migrate_ev_charger_fields` stops copying `ev_departure_time`.**
The root key remains in `DEPRECATED_KEYS` so it's swept as before; it just no longer lands in the charger entry first. Other migrations in that function (switch_entity, replan flags, current control) are untouched.

**D5 — Frontend removal is complete, not cosmetic.**
Remove `departure_time` and `penalty_levels` from `EVChargerEntity`, the new-charger defaults, and the inline Penalty Levels UI in `EntityArrayEditor.tsx`; delete `PenaltyLevelsEditor.tsx`; remove the `penalty_levels` field-type branches from `SettingsField.tsx`, `types.ts`, `utils.ts`; remove `penalty_levels` from the config type in `lib/api.ts`. Rationale: leaving the type fields means the settings page keeps round-tripping (re-adding) keys the migration just stripped.

**D6 — Delete `calculate_ev_deadline` and its two test files outright.** No deprecation shim: it is unreachable production code.

## Risks / Trade-offs

- [Settings save round-trips a full config: if the frontend still sends `penalty_levels` from cached state, saves could re-plant stripped keys] → D5 removes the fields from the frontend types/defaults in the same change; migration also runs on every startup, so any re-planted key is stripped on next boot.
- [Some other consumer of `penalty_levels` exists that grep missed (e.g. dynamic `config.get`)] → verified: only `backend/health.py` checks the *old* `executor.ev_charger.penalty_levels` location as a deprecation warning (untouched), and a comment in `config.py`. Implementation task re-verifies with a repo-wide grep before deleting.
- [User downgrades after migration and wants their old penalty_levels back] → accepted per user decision; automatic migration backups exist under the persistent backup dir.
- [Tests elsewhere construct configs containing `departure_time`/`penalty_levels`] → migration must tolerate them (it strips silently); test suite run in the verify task catches any assertion on the old validators.

## Migration Plan

Single release: migration step ships with the validator removal, so upgraded users are healed on first startup (migration rewrites config with backup) and can save settings immediately even before restart (validators gone). Rollback = restore config from the automatic backup and downgrade.

## Open Questions

(none — backup question resolved: migration already backs up automatically)
