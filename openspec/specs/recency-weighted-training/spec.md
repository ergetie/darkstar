## Purpose

The recency-weighted training capability applies exponential decay sample weights when training LightGBM models for load and PV forecasting. This allows recent observations to have higher influence than older observations while retaining long-term seasonal patterns. This approach replaces the previous corrector layer that applied post-hoc corrections to base model predictions.

## Requirements

### Requirement: Exponential recency weighting for training samples
The training system SHALL apply exponential decay sample weights when training LightGBM models, so that recent observations have higher influence than older observations while retaining long-term seasonal patterns.

#### Scenario: Weight calculation for recent data
- **WHEN** training with a sample from 1 day ago
- **THEN** the sample weight SHALL be approximately 1.0 (near-full weight)

#### Scenario: Weight calculation for moderately old data
- **WHEN** training with a sample from 30 days ago
- **THEN** the sample weight SHALL be approximately 0.5 (half-life point)

#### Scenario: Weight calculation for old seasonal data
- **WHEN** training with a sample from 180 days ago
- **THEN** the sample weight SHALL be approximately 0.05 (low but non-zero, preserving seasonal signal)

#### Scenario: Weights passed to LightGBM
- **WHEN** calling `LGBMRegressor.fit()`
- **THEN** the `sample_weight` parameter SHALL be provided with the computed decay weights

### Requirement: Use all available historical data
The training system SHALL train on all valid observations available in the database, with no hard cap on the training window.

#### Scenario: Training data selection
- **WHEN** loading slot observations for training
- **THEN** the system SHALL load all rows from `slot_observations` that pass validation filters (load > 0.001, within max_kwh cap)

#### Scenario: Existing data validation preserved
- **WHEN** loading training data
- **THEN** the existing filters for zero-artifacts (`load_kwh > 0.001`), sensor spikes (`load_kwh <= max_kwh`, `pv_kwh <= max_kwh`), and null values SHALL continue to apply

### Requirement: Configurable decay half-life
The decay half-life SHALL default to 30 days and be configurable via system config.

#### Scenario: Default half-life
- **WHEN** no explicit half-life is configured
- **THEN** the system SHALL use a 30-day half-life for the exponential decay

#### Scenario: Custom half-life
- **WHEN** a `training.recency_half_life_days` value is set in system config
- **THEN** the system SHALL use that value as the decay half-life

### Requirement: Recency weights align to training rows by label
The training system SHALL align recency sample weights to training rows by their DataFrame label, so that rows dropped or gapped during preprocessing (e.g. an un-parseable `slot_start` removed by `dropna`) neither crash training nor attach weights to the wrong rows.

#### Scenario: Observation with an un-parseable timestamp
- **WHEN** the `slot_observations` set contains a row whose `slot_start` fails to parse and is dropped, leaving a gapped index
- **THEN** training SHALL complete without raising `IndexError`
- **AND** each surviving row SHALL receive the recency weight computed for that same row

#### Scenario: Contiguous data is unaffected
- **WHEN** all observations have valid timestamps and the index is contiguous
- **THEN** the computed weights SHALL be identical to the previous positional behavior (no regression for the normal path)
