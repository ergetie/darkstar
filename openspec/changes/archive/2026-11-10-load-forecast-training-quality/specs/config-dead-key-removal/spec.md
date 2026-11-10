## ADDED Requirements

### Requirement: Dead load safety margin keys removed
`forecasting.load_safety_margin_percent` and `learning.max_daily_param_change.load_safety_margin_percent` SHALL be removed from `config.default.yaml`, the sample config, the settings UI field definitions, the settings search guide and the help text. Config migration SHALL delete both keys from an existing `config.yaml`, idempotently, without touching other keys.

#### Scenario: Existing config migrated
- **WHEN** a config contains both keys
- **THEN** migration SHALL remove them, keep all other keys and report a change

#### Scenario: Already clean
- **WHEN** neither key exists
- **THEN** migration SHALL make no change

#### Scenario: Template merge does not re-add
- **WHEN** the default template is merged after migration
- **THEN** the keys SHALL NOT reappear
