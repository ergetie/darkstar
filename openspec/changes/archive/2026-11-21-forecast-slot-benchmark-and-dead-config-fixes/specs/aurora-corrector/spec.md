## ADDED Requirements

### Requirement: Stale corrector model files are purged at startup
Model bootstrap at application startup SHALL delete `pv_error.lgb` and `load_error.lgb` from the runtime models directory, its `defaults/` copy, and every training backup folder, and SHALL log each deletion. It SHALL delete no other file, SHALL NOT fail when the files or folders are absent, and SHALL do nothing on a second run. The shipped default models SHALL NOT include `load_error.lgb`. This applies in Docker and Home Assistant add-on modes, which start the same application.

#### Scenario: Stale files present
- **WHEN** the application starts and `load_error.lgb` exists in the runtime models directory and in a training backup
- **THEN** both files are deleted and each deletion is logged
- **AND** the real model files (`*_model*.lgb`) are untouched

#### Scenario: Second startup
- **WHEN** the application starts again
- **THEN** nothing is deleted and no error is logged

#### Scenario: Backup restore
- **WHEN** a training backup is restored after the purge
- **THEN** no `*_error.lgb` file reappears in the models directory

#### Scenario: Health check
- **WHEN** the health check reports model files
- **THEN** it does not list `pv_error.lgb` or `load_error.lgb` as optional models

### Requirement: Dead error-correction config keys are removed
Config migration SHALL remove `learning.error_correction_enabled`, `learning.auto_tune_enabled` and `automation.ml_training.error_correction_enabled`, as no component reads them.

#### Scenario: Existing config
- **WHEN** a config holding the three keys is migrated
- **THEN** the keys are gone and sibling keys such as `learning.reflex_enabled` and `automation.ml_training.enabled` are kept
