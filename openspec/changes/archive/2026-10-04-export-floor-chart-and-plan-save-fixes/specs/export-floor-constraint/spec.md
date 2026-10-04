## ADDED Requirements

### Requirement: Export floor setting targets the planner key
The Settings field for the export prevention floor SHALL read and write `export.export_floor_soc_percent`, the key consumed by the planner, and SHALL NOT use `executor.override.low_soc_export_floor`. The field's search entries (guide and alias keys) SHALL reference the same key. A value saved through Settings SHALL be the value the next planner run passes to `KeplerConfig.export_floor_soc_percent`.

#### Scenario: Saved value reaches the planner
- **WHEN** the user sets the Export Prevention Floor to 30 in Settings and saves
- **THEN** `config.yaml` contains `export.export_floor_soc_percent: 30`
- **AND** the next planner run builds `KeplerConfig.export_floor_soc_percent` as 30.0

#### Scenario: Field shows the value in use
- **GIVEN** `export.export_floor_soc_percent` is 20 in the effective configuration
- **WHEN** the user opens the Settings battery section
- **THEN** the Export Prevention Floor field shows 20

#### Scenario: Legacy key is not written
- **WHEN** the user saves any value for the Export Prevention Floor
- **THEN** the saved configuration does not contain `executor.override.low_soc_export_floor`
