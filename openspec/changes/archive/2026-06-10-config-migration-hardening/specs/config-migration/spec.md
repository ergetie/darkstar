## ADDED Requirements

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
