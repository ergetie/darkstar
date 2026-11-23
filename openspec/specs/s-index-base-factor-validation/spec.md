# Spec: S-Index Base Factor Validation

## Purpose
Warn at config save when `s_index.base_factor` is outside its sane range. Warn-only, through the existing save validation.

## Requirements

### Requirement: Base factor range warning on save
The config save validation SHALL return a warning (not an error) with field `s_index.base_factor` when `s_index.base_factor` is a number below 1.0 or above `s_index.max_factor`. When `max_factor` is absent the default 1.5 SHALL be used; the upper comparison SHALL be skipped when `max_factor` is not a number. The warning SHALL NOT block the save and SHALL be returned by both the save and the validate endpoints.

#### Scenario: Base factor below one
- **WHEN** `s_index.base_factor` is 0.9
- **THEN** the save succeeds and the response contains a warning for `s_index.base_factor`

#### Scenario: Base factor above max
- **WHEN** `s_index.base_factor` is 1.6 and `s_index.max_factor` is 1.5
- **THEN** the save succeeds and the response contains a warning

#### Scenario: Valid base factor
- **WHEN** `s_index.base_factor` is 1.1 and `s_index.max_factor` is 1.5
- **THEN** no `s_index` warning is returned

#### Scenario: Absent section
- **WHEN** the config has no `s_index` section or no `base_factor`
- **THEN** no `s_index` warning is returned
