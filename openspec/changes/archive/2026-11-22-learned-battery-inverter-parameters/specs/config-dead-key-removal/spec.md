## MODIFIED Requirements

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

## ADDED Requirements

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
