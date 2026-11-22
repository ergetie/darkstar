## MODIFIED Requirements

### Requirement: Analytical pipelines filter spike rows at read time
All analytical read paths that consume `pv_kwh` or `load_kwh` from `slot_observations` SHALL exclude rows where those values exceed `max_kwh_per_slot`.

#### Scenario: Analyst bias calculation excludes spike rows
- **WHEN** `Analyst._fetch_observations` fetches rows for bias analysis
- **THEN** rows where `load_kwh` or `pv_kwh` exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: Reflex accuracy analysis excludes spike rows
- **WHEN** any forecast-versus-actual comparison reads actual energy columns (formerly the Reflex reader)
- **THEN** rows where the actual energy column exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: MAE metrics exclude spike rows
- **WHEN** `LearningStore.calculate_metrics` computes forecast MAE
- **THEN** the query SHALL exclude rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot`

#### Scenario: ML model training excludes spike rows
- **WHEN** `ml/train.py` `_load_slot_observations` loads data for Aurora model training
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded from training data

#### Scenario: ML error correction training excludes spike rows
- **WHEN** `ml/corrector.py` `_load_training_frame` loads data for error correction model training
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: ML evaluation metrics exclude spike rows
- **WHEN** `ml/evaluate.py` `_compute_mae` calculates forecast accuracy metrics
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded from MAE calculation
