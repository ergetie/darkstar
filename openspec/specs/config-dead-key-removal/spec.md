# Capability: Config Dead Key Removal

## Purpose

Remove config keys that no code reads (load_safety_margin_percent and its learning limit) from defaults, UI and existing configs.

## Requirements

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

### Requirement: Dead error-correction and auto-tune keys removed
Config migration SHALL remove `learning.error_correction_enabled`, `learning.auto_tune_enabled` and `automation.ml_training.error_correction_enabled` from user configs. Removal SHALL be idempotent, SHALL tolerate missing or non-mapping sections, SHALL keep all other keys, and the template merge SHALL NOT re-add them. The config version SHALL NOT change.

#### Scenario: Existing config migrated
- **WHEN** a config containing the three keys is migrated
- **THEN** none of them remains and `learning.enable`, `automation.ml_training.enabled` and `automation.ml_training.run_days` are unchanged

#### Scenario: Already clean or malformed
- **WHEN** the config lacks the keys, or `learning` or `automation.ml_training` is null or not a mapping
- **THEN** migration reports no change and raises no error

#### Scenario: Template merge does not re-add
- **WHEN** the full migration runs on a config that held the keys
- **THEN** the saved config does not contain them

### Requirement: Dead Reflex config keys are removed
Config migration SHALL remove `learning.reflex_enabled`, `learning.max_daily_param_change` (whole mapping), `learning.min_sample_threshold` and `learning.min_improvement_threshold`. It SHALL be idempotent, tolerate missing or non-mapping sections, keep every other key (including values Reflex once wrote, such as `forecasting.pv_confidence_percent`), and the template merge SHALL NOT re-add them.

#### Scenario: Existing config
- **WHEN** a config with the four keys and `forecasting.pv_confidence_percent` 95 is migrated
- **THEN** the four keys are gone and the confidence value is still 95

#### Scenario: Malformed learning section
- **WHEN** `learning` is null or not a mapping
- **THEN** migration reports no change and raises no error

#### Scenario: Template merge does not re-add
- **WHEN** the default template is merged after migration
- **THEN** the removed keys do not reappear
