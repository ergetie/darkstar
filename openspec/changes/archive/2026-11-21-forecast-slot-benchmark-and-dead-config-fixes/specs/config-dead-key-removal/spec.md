## ADDED Requirements

### Requirement: Dead error-correction and auto-tune keys removed
Config migration SHALL remove `learning.error_correction_enabled`, `learning.auto_tune_enabled` and `automation.ml_training.error_correction_enabled` from user configs. Removal SHALL be idempotent, SHALL tolerate missing or non-mapping sections, SHALL keep all other keys, and the template merge SHALL NOT re-add them. The config version SHALL NOT change.

#### Scenario: Existing config migrated
- **WHEN** a config containing the three keys is migrated
- **THEN** none of them remains and `learning.reflex_enabled`, `automation.ml_training.enabled` and `automation.ml_training.run_days` are unchanged

#### Scenario: Already clean or malformed
- **WHEN** the config lacks the keys, or `learning` or `automation.ml_training` is null or not a mapping
- **THEN** migration reports no change and raises no error

#### Scenario: Template merge does not re-add
- **WHEN** the full migration runs on a config that held the keys
- **THEN** the saved config does not contain them
