## Purpose

The AURORA corrector capability has been removed. The corrector layer (stats bias + ML error model) was architecturally coupled to the base model version, causing stale corrections after every base model retrain. The base model with recency weighting now replaces the corrector's purpose.

**Note**: This spec file is kept for historical reference. All corrector functionality has been migrated to the recency-weighted base model approach.

## Requirements

### Requirement: Base model output is used directly, without corrector adjustment
The forecast API MUST use the base model's predictions directly as the `final.load_kwh` and `final.pv_kwh` values, with no corrector-layer (stats bias + ML error model) adjustment applied. Correction columns in the database schema MUST be preserved for backward compatibility but MUST NOT be read or applied when assembling forecast records. Error correction and auto-tuning toggles MUST NOT appear in the UI.

#### Scenario: Final forecast fields equal base model output
- **WHEN** the forecast API assembles a forecast record's `final` field
- **THEN** `final.load_kwh` SHALL equal the base model's load forecast (`base_load_forecast_kwh`, falling back to `load_forecast_kwh`) with no correction applied
- **AND** `final.pv_kwh` SHALL equal the hybrid physics + ML PV forecast with no corrector-layer adjustment applied
