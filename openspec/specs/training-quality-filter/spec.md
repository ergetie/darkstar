## Purpose

Keep quality-flagged-bad `slot_observations` rows (e.g. the January 2026 data-corruption cluster) out of the ML training set, so corrupted historical data never trains the models, without deleting or rewriting historical data.

## Requirements

### Requirement: ML training excludes quality-flagged slots

The ML training data loader SHALL exclude `slot_observations` rows whose `quality_flags` marks them as bad (the exclusion set) from the training set. Rows with no flag (or a benign/clean flag) SHALL continue to be included. The exclusion SHALL be applied wherever training data is assembled, so flagged-bad periods (e.g. the January 2026 corruption cluster) never train the models.

#### Scenario: A slot is flagged for exclusion

- **WHEN** a `slot_observations` row has a `quality_flags` value in the exclusion set
- **THEN** the training data loader omits that row from the returned training set

#### Scenario: An unflagged slot

- **WHEN** a `slot_observations` row has no `quality_flags` (or a value not in the exclusion set)
- **THEN** the row is included in the training set as before

#### Scenario: Existing historical data is unchanged

- **WHEN** this change is applied
- **THEN** no historical `slot_observations` rows are deleted or rewritten; only the training-time query filters them
