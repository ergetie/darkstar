## MODIFIED Requirements

### Requirement: Diagnostics bundle download
The system SHALL provide a single zip download containing a consistent snapshot of `planner_learning.db`, `config.yaml` exactly as stored on disk, the log file, `schedule.json`, the JSON output of the version, status, health and monitors endpoints, the load balancer trace as `balancer_trace.json`, and a `manifest.json`.

#### Scenario: Bundle contents
- **WHEN** a user requests the diagnostics bundle on a healthy system
- **THEN** the zip contains `planner_learning.db`, `config.yaml`, `darkstar.log`, `schedule.json`, `version.json`, `status.json`, `health.json`, `monitors.json`, `balancer_trace.json` and `manifest.json`

#### Scenario: Config is exported as is
- **WHEN** the bundle is created
- **THEN** `config.yaml` in the zip is byte-identical to the file on disk

#### Scenario: Secrets file is never included
- **WHEN** the bundle is created
- **THEN** it contains no file derived from `secrets.yaml`

#### Scenario: Database is in the bundle
- **WHEN** the bundle is created while Darkstar is running
- **THEN** the `planner_learning.db` inside the zip opens without error and passes `PRAGMA integrity_check`
- **AND** it is a consistent snapshot, the same as the standalone database download

#### Scenario: One item fails
- **WHEN** an item is missing or its source fails, for example `schedule.json` does not exist or Home Assistant is unreachable for status
- **THEN** the bundle is still returned with the remaining items
- **AND** `manifest.json` lists that item with the reason it is missing

#### Scenario: Manifest content
- **WHEN** the bundle is created
- **THEN** `manifest.json` records the Darkstar version, the export time in UTC, and for every item either that it is included or the error
