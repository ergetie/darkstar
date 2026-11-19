# Spec Delta

## Purpose
Bound disk use of application logs and container logs.

## ADDED Requirements

### Requirement: Size-rotated application log
The application log SHALL rotate at 10 MiB and keep 5 backups.

#### Scenario: Rollover
- **WHEN** the log exceeds 10 MiB
- **THEN** it rolls to `darkstar.log.1` and at most 5 backups exist

### Requirement: Clear logs removes backups
Clearing logs SHALL truncate the active log and delete rotated backups.

#### Scenario: Clear
- **WHEN** logs are cleared with backups present
- **THEN** the active file is empty and no `darkstar.log.N` files remain

### Requirement: Diagnostics includes recent rotated log
The diagnostics bundle SHALL include `darkstar.log.1` when present and list it in the manifest.

#### Scenario: Bundle
- **WHEN** a backup `darkstar.log.1` exists
- **THEN** the bundle contains it

### Requirement: Container log limits
`docker-compose.yml` SHALL set json-file logging with max-size 10m and max-file 3 for the darkstar and updater services.

#### Scenario: Compose config
- **WHEN** compose is parsed
- **THEN** both services carry those options
