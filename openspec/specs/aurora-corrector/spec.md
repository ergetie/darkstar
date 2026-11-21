## Purpose

The AURORA corrector capability has been removed. The corrector layer (stats bias + ML error model) was architecturally coupled to the base model version, causing stale corrections after every base model retrain. The base model with recency weighting now replaces the corrector's purpose.

**Note**: This spec file is kept for historical reference. All corrector functionality has been migrated to the recency-weighted base model approach.

## Requirements

### Requirement: Base model output is used directly, without corrector adjustment
The forecast API MUST use the base model's predictions directly as the `final.load_kwh` and `final.pv_kwh` values, with no corrector-layer (stats bias + ML error model) adjustment applied. Error correction and auto-tuning toggles MUST NOT appear in the UI.

#### Scenario: Final forecast fields equal base model output
- **WHEN** the forecast API assembles a forecast record's `final` field
- **THEN** `final.load_kwh` SHALL equal the base model's load forecast (`base_load_forecast_kwh`, falling back to `load_forecast_kwh`) with no correction applied
- **AND** `final.pv_kwh` SHALL equal the hybrid physics + ML PV forecast with no corrector-layer adjustment applied

### Requirement: No corrector surfaces in API or UI
The system SHALL NOT expose corrector status or correction history in any API response or UI component. Leftover `*_error.lgb` files in the models directory SHALL NOT affect the Model Training display.

#### Scenario: Leftover corrector files present
- **WHEN** `load_error.lgb` or `pv_error.lgb` exist in the models directory
- **THEN** the Model Training card shows no Corrector tile
- **AND** the Main Models age is computed only from `*model*` files

#### Scenario: Forecast API response
- **WHEN** a client requests the Aurora forecast dashboard data
- **THEN** the response contains no `correction_history` field

### Requirement: Corrector columns are removed from the database on upgrade
The database migration SHALL drop `pv_correction_kwh`, `load_correction_kwh` and `correction_source` from `slot_forecasts` without losing any other data, and SHALL be idempotent and reversible.

#### Scenario: Existing install upgrades
- **WHEN** `alembic upgrade head` runs on a DB that has the correction columns
- **THEN** the columns are removed
- **AND** every `slot_forecasts` row and all other column values, indexes and unique constraints are preserved

#### Scenario: Columns already absent
- **WHEN** the migration runs on a DB without those columns
- **THEN** it completes without error and makes no changes

#### Scenario: Downgrade
- **WHEN** `alembic downgrade -1` runs after the upgrade
- **THEN** the three columns are re-added with defaults `0`, `0` and `'none'`

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
