# Spec: Config Migration

## Purpose

Defines the behaviour of `migrate_config()` — the startup routine responsible for bringing user config files up to the current schema. The migration MUST be safe, idempotent, and non-destructive: it may only write when a change is required, must preserve user values, and must never corrupt a config file that fails structural validation.

## Requirements

### Requirement: Fully-migrated configs are not modified on startup
A config already at `config_version=2` with no deprecated keys SHALL pass through `migrate_config()` without any file write occurring.

#### Scenario: Idempotent startup for clean config
- **WHEN** `migrate_config()` is called with a config at `config_version=2` and no deprecated keys present
- **THEN** the config file SHALL NOT be written to disk
- **AND** the function SHALL complete without error

#### Scenario: Deprecated keys are still removed at startup
- **WHEN** `migrate_config()` is called with a config at `config_version=2` that contains a deprecated root-level key (e.g., `deferrable_loads`, `ev_charger`, `solar_array`, `version`, `schedule_future_only`)
- **THEN** the deprecated key SHALL be removed from the written config
- **AND** all other user values SHALL be preserved

#### Scenario: Deprecated nested keys are still removed at startup
- **WHEN** `migrate_config()` is called and the config contains deprecated keys under `executor.inverter` (e.g., `work_mode_entity`, `soc_target_entity`) or deprecated flat keys under `water_heating`
- **THEN** those deprecated nested keys SHALL be removed
- **AND** all sibling keys that are not deprecated SHALL be preserved

### Requirement: Migration sets config_version explicitly
`migrate_config()` SHALL set `config_version` to the current schema version (2) as a dedicated migration step, independent of the template merge. This step SHALL run whenever `config_version` is missing or lower than the current version, and SHALL mark the config as changed so the write occurs even if the template merge is skipped (default template missing, or unreadable).

#### Scenario: Missing config_version is set without the template merge
- **WHEN** `migrate_config()` runs on a config that has no `config_version`
- **AND** the default template is missing or fails to load (template merge skipped)
- **THEN** the written config SHALL have `config_version: 2`
- **AND** the write SHALL occur even though the template merge did not run

#### Scenario: Config version below current is raised
- **WHEN** `migrate_config()` runs on a config with `config_version: 1`
- **THEN** the written config SHALL have `config_version: 2`

#### Scenario: Higher config version is not downgraded
- **WHEN** `migrate_config()` runs on a config with `config_version` greater than the current version
- **THEN** the `config_version` SHALL NOT be lowered

#### Scenario: Clean current-version config still writes nothing
- **WHEN** `migrate_config()` runs on a config already at `config_version: 2` with no deprecated keys and no other migration changes
- **THEN** no file write SHALL occur (idempotency preserved)

### Requirement: Critical user values are preserved through template merge
The template merge step SHALL never overwrite user-configured values with template defaults.

#### Scenario: User values survive merge with updated template
- **WHEN** `migrate_config()` runs the template merge and the default template has a key with a different value than the user config
- **THEN** the user's value SHALL be kept in the final config
- **AND** new keys present in the template but absent in the user config SHALL be added with their default values

#### Scenario: Backup is created before any write
- **WHEN** `migrate_config()` determines a write is needed
- **THEN** a timestamped backup of the current config SHALL be created before writing
- **AND** the backup SHALL be stored in the persistent backup directory

### Requirement: Corrupt or missing config is handled safely
`migrate_config()` SHALL abort without writing if the config fails structure validation, preventing data loss.

#### Scenario: Structurally invalid config aborts migration
- **WHEN** `migrate_config()` loads a config that fails `_validate_config_structure()`
- **THEN** migration SHALL be aborted
- **AND** the config file SHALL NOT be modified
- **AND** an error SHALL be logged

#### Scenario: Missing config file is a no-op
- **WHEN** `migrate_config()` is called and the config file does not exist
- **THEN** the function SHALL return without error
- **AND** no file SHALL be created

### Requirement: Migrate global EV departure time into first charger
The migration SHALL copy `ev_departure_time` from root level into the first enabled `ev_chargers[]` entry as `departure_time`, only if that entry does not already have a `departure_time` value set.

#### Scenario: Global departure time migrated to first charger
- **WHEN** `ev_departure_time: "07:00"` exists at root level
- **AND** the first enabled charger has no `departure_time` field
- **THEN** the first enabled charger SHALL have `departure_time: "07:00"` after migration

#### Scenario: Existing per-device departure time preserved
- **WHEN** `ev_departure_time: "07:00"` exists at root level
- **AND** the first enabled charger already has `departure_time: "08:00"`
- **THEN** the charger's `departure_time` SHALL remain `"08:00"`

#### Scenario: No enabled chargers skips migration
- **WHEN** `ev_departure_time` exists but no chargers have `enabled: true`
- **THEN** the migration SHALL skip this step without error

### Requirement: Migrate executor EV charger settings into first charger
The migration SHALL copy `executor.ev_charger.switch_entity`, `executor.ev_charger.replan_on_plugin`, and `executor.ev_charger.replan_on_unplug` into the first enabled `ev_chargers[]` entry, only if those fields are not already set on that entry.

This migration step SHALL run **before** `remove_deprecated_keys()` is called. The deprecated key removal step MUST NOT execute before all field migration steps complete, as the migration reads from paths that are listed as deprecated.

#### Scenario: Switch entity migrated
- **WHEN** `executor.ev_charger.switch_entity: "switch.wallbox"` exists
- **AND** the first enabled charger has no `switch_entity` field
- **THEN** the first enabled charger SHALL have `switch_entity: "switch.wallbox"` after migration

#### Scenario: Replan settings migrated with defaults preserved
- **WHEN** `executor.ev_charger.replan_on_plugin: true` and `executor.ev_charger.replan_on_unplug: false` exist
- **AND** the first enabled charger has no replan fields
- **THEN** the first enabled charger SHALL have `replan_on_plugin: true` and `replan_on_unplug: false`

#### Scenario: Existing per-device settings preserved
- **WHEN** the first enabled charger already has `switch_entity: "switch.other"`
- **THEN** that value SHALL NOT be overwritten by the executor.ev_charger migration

#### Scenario: Migration runs before deprecated key removal
- **WHEN** `executor.ev_charger.switch_entity` is listed in `DEPRECATED_NESTED_KEYS`
- **AND** migration has not yet run
- **THEN** `_migrate_ev_charger_fields()` SHALL execute before `remove_deprecated_keys()`
- **AND** the switch entity value SHALL be present in `ev_chargers[0]` after both steps complete

### Requirement: Deprecate migrated global EV settings
After migration, the following paths SHALL be added to the deprecated keys registry: `ev_departure_time` (root level), `executor.ev_charger.switch_entity`, `executor.ev_charger.replan_on_plugin`, `executor.ev_charger.replan_on_unplug`. These SHALL be removed from the config file during the deprecated-key cleanup phase.

#### Scenario: Deprecated keys removed after migration
- **WHEN** migration completes and deprecated key removal runs
- **THEN** `ev_departure_time` SHALL no longer exist at root level
- **AND** `executor.ev_charger.switch_entity`, `executor.ev_charger.replan_on_plugin`, `executor.ev_charger.replan_on_unplug` SHALL no longer exist

#### Scenario: executor.ev_charger section cleaned up
- **WHEN** all keys under `executor.ev_charger` have been migrated and deprecated
- **AND** no non-deprecated keys remain under `executor.ev_charger`
- **THEN** the entire `executor.ev_charger` section SHALL be removed

### Requirement: Migration is idempotent
Running the migration multiple times SHALL produce the same result. The migration SHALL only copy values when the target field is absent or empty.

#### Scenario: Second migration run is a no-op
- **WHEN** migration has already run once (per-device fields populated, deprecated keys removed)
- **AND** migration runs again on startup
- **THEN** no config file write SHALL occur

### Requirement: Config default template updated
The `config.default.yaml` template SHALL include the new per-device fields in `ev_chargers[]` entries (`departure_time`, `switch_entity`, `replan_on_plugin`, `replan_on_unplug`) with appropriate defaults. The global `ev_departure_time` and `executor.ev_charger` section SHALL be removed from the template.

#### Scenario: New installation gets per-device defaults
- **WHEN** a new user starts with `config.default.yaml`
- **THEN** each `ev_chargers[]` entry SHALL include `departure_time: ""`, `switch_entity: ""`, `replan_on_plugin: true`, `replan_on_unplug: false`
- **AND** no global `ev_departure_time` or `executor.ev_charger` section SHALL exist
