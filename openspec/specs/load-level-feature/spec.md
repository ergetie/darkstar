# Capability: Load Level Feature

## Purpose

Give the load model a recent-load-level input (mean of the last 7 clean days) so forecasts follow changes in household consumption.

## Requirements

### Requirement: Load level feature
Load models SHALL include `load_level_7d`: for a slot on local day D, the mean daily load (kWh) over the complete local days D-7..D-1 (at least 90 % of slots) that survive the training data rule. Day D and later days SHALL never contribute. The value is constant within day D. It SHALL be a load-model feature only, not a PV feature.

#### Scenario: No leakage in training
- **WHEN** training computes the feature for day D
- **THEN** only observations dated before D SHALL be used

#### Scenario: Train/inference parity
- **WHEN** the same history is given to training and inference
- **THEN** one shared function SHALL give identical values

### Requirement: Missing recent days
If fewer than 3 clean complete days exist in D-7..D-1, the value SHALL be that of the most recent day with at least 3, held constant; if none exists it SHALL be NaN. Forecast values SHALL NOT fill the level.

#### Scenario: Forecast day tomorrow
- **WHEN** today is incomplete
- **THEN** tomorrow's level SHALL use the complete days before today, if at least 3

### Requirement: Schema versioning and automatic retrain
Load model sidecars SHALL carry `schema_version`. Inference SHALL load a load model only when version and feature names match; otherwise it SHALL warn, not use the model, use the existing degraded baseline path and request a retrain. The scheduler SHALL start a training run when a load model was rejected for schema mismatch, at most once per hour. PV model validation and feature list SHALL be unchanged.

#### Scenario: Upgrade
- **WHEN** a pre-change load model is found
- **THEN** it SHALL be rejected, a retrain SHALL be triggered, and PV models SHALL still load

#### Scenario: Retrain loop guard
- **WHEN** retraining fails repeatedly
- **THEN** it SHALL be attempted at most once per hour
