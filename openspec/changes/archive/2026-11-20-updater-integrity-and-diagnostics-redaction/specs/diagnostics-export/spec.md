## MODIFIED Requirements

### Requirement: Diagnostics bundle download
The system SHALL provide a single zip download containing a consistent snapshot of `planner_learning.db` with secret values in stored config versions masked, a redacted `config.yaml`, the redacted log file, redacted `schedule.json`, the redacted JSON output of the version, status, health and monitors endpoints, the load balancer trace as `balancer_trace.json`, and a `manifest.json`.

#### Scenario: Bundle contents
- **WHEN** a user requests the diagnostics bundle on a healthy system
- **THEN** the zip contains `planner_learning.db`, `config.yaml`, `darkstar.log`, `schedule.json`, `version.json`, `status.json`, `health.json`, `monitors.json`, `balancer_trace.json` and `manifest.json`

#### Scenario: Config is exported as is
- **WHEN** the config has no secret-named keys, coordinates or URLs to redact
- **THEN** `config.yaml` in the zip is byte-identical to the file on disk

#### Scenario: Secrets file is never included
- **WHEN** the bundle is created
- **THEN** it contains no file derived from `secrets.yaml`

#### Scenario: Database is in the bundle
- **WHEN** the bundle is created while Darkstar is running
- **THEN** the `planner_learning.db` inside the zip opens without error and passes `PRAGMA integrity_check`
- **AND** it is a consistent snapshot, the live database is unchanged, and no tables other than `config_versions` differ from the standalone snapshot

#### Scenario: One item fails
- **WHEN** an item is missing or its source fails, for example `schedule.json` does not exist or Home Assistant is unreachable for status
- **THEN** the bundle is still returned with the remaining items
- **AND** `manifest.json` lists that item with the reason it is missing

#### Scenario: Manifest content
- **WHEN** the bundle is created
- **THEN** `manifest.json` records the Darkstar version, the export time in UTC, whether redaction was applied, and for every item either that it is included or the error

## ADDED Requirements

### Requirement: Text redaction
Text in the diagnostics bundle and in the log download SHALL be redacted of identifying data while private IPs, local names and known service hosts stay readable. Redacted output of valid JSON text SHALL remain valid JSON.

#### Scenario: Rules applied
- **WHEN** text is redacted
- **THEN** URL credentials, paths, queries, token-like parameters and bearer values are removed
- **AND** URL hosts that are not private, local or known public services become `<redacted-host>`, public IPv4 addresses become `<redacted-ip>`, and numeric latitude/longitude values become `<redacted>` (`"<redacted>"` for unquoted JSON values)

#### Scenario: Home Assistant over a public name
- **WHEN** a log line contains `https://myhome.ui.nabu.casa/api/states?token=abc`
- **THEN** the exported line contains neither the host, the path nor the token

#### Scenario: Local Home Assistant stays diagnosable
- **WHEN** a log line contains `http://192.168.0.100:8123`
- **THEN** the exported line still contains `http://192.168.0.100:8123`

#### Scenario: Coordinates in text
- **WHEN** a payload contains `"latitude": 55.123`
- **THEN** the exported payload contains no coordinate value

### Requirement: Config redaction
The bundle config SHALL keep comments, order and all values except secret-named keys, coordinates and URL strings. Entity ids, device names, tariffs and hardware parameters SHALL be kept. Secret-named keys (token, secret, password, api key, webhook, credential, authorization, bearer, private key, at any depth) SHALL become `<redacted>` when non-empty. Latitude and longitude SHALL be rounded to one decimal and URL strings follow text redaction.

#### Scenario: Secret-named key
- **WHEN** config contains `notifications: {discord_webhook: "https://discord.com/api/webhooks/1/x"}` or `api_key: abc`
- **THEN** the bundle config shows `<redacted>` for both and an empty `api_key: ""` stays empty

#### Scenario: Coordinates rounded
- **WHEN** config has `latitude: 55.123` and `longitude: 13.456`
- **THEN** the bundle config has `55.1` and `13.5`

#### Scenario: Entities kept
- **WHEN** config has `sensor: sensor.battery_soc`
- **THEN** the bundle config still has `sensor.battery_soc`

#### Scenario: Unparseable config
- **WHEN** `config.yaml` is not valid YAML
- **THEN** the raw file is never used as a fallback, the bundle has no `config.yaml` and the manifest lists `config.yaml` as `error: could not redact config`

### Requirement: Secrets masked in bundled config versions
In the bundled database copy, secret-named keys inside stored config versions (`config_versions.yaml_blob`) SHALL be masked with the same rule as the config. A stored version that cannot be parsed SHALL be replaced by a placeholder. All other database content SHALL be left intact.

#### Scenario: Stored version with a secret
- **WHEN** a stored config version contains `api_key: abc`
- **THEN** the bundled copy has `<redacted>` for it and the live database still has the original

#### Scenario: Masking fails
- **WHEN** masking the bundled database copy raises an error
- **THEN** the bundle has no `planner_learning.db` and the manifest lists it as `error: could not mask config versions`
- **AND** the rest of the bundle is still returned

#### Scenario: Other tables untouched
- **WHEN** the bundle database is compared with the live database
- **THEN** every table except `config_versions` has identical rows

### Requirement: Redacted log download
`GET /api/system/logs` SHALL return the log with text redaction applied. The raw configuration download and the raw database snapshot SHALL remain unredacted explicit backups.

#### Scenario: Log download
- **WHEN** the log contains a public-host URL
- **THEN** the downloaded log shows `<redacted-host>` for it
