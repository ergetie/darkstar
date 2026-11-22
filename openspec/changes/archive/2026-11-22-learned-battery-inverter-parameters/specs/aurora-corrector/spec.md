## MODIFIED Requirements

### Requirement: Dead error-correction config keys are removed
Config migration SHALL remove `learning.error_correction_enabled`, `learning.auto_tune_enabled` and `automation.ml_training.error_correction_enabled`, as no component reads them.

#### Scenario: Existing config
- **WHEN** a config holding the three keys is migrated
- **THEN** the keys are gone and sibling keys such as `learning.enable` and `automation.ml_training.enabled` are kept
