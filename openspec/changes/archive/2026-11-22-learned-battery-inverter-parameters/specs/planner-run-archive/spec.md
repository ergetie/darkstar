## ADDED Requirements

### Requirement: Records carry the battery parameters the run used
Each archive record SHALL include the effective battery efficiencies the run planned with and, per parameter, their source (`locked`, `learned`, `default`, `config`, `expired`), so a replay can reproduce the run and the evaluation can compare config and learned values. Older records without the field SHALL stay valid.

#### Scenario: Learned values used
- **WHEN** a run plans with learned efficiencies
- **THEN** its record lists the charge and discharge efficiency used and the source of each component

#### Scenario: Config fallback used
- **WHEN** a run plans with the configured efficiencies
- **THEN** the record lists them with source `config`

#### Scenario: Older record
- **WHEN** a record written before this change is read
- **THEN** it loads without error and the field is treated as absent
