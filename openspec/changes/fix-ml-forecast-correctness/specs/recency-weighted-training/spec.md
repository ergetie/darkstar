## ADDED Requirements

### Requirement: Recency weights align to training rows by label
The training system SHALL align recency sample weights to training rows by their DataFrame label, so that rows dropped or gapped during preprocessing (e.g. an un-parseable `slot_start` removed by `dropna`) neither crash training nor attach weights to the wrong rows.

#### Scenario: Observation with an un-parseable timestamp
- **WHEN** the `slot_observations` set contains a row whose `slot_start` fails to parse and is dropped, leaving a gapped index
- **THEN** training SHALL complete without raising `IndexError`
- **AND** each surviving row SHALL receive the recency weight computed for that same row

#### Scenario: Contiguous data is unaffected
- **WHEN** all observations have valid timestamps and the index is contiguous
- **THEN** the computed weights SHALL be identical to the previous positional behavior (no regression for the normal path)
