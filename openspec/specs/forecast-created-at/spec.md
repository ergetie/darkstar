## Purpose

Defines how stored forecast rows record their `created_at` timestamp so it reflects the most recent write.

## Requirements

### Requirement: Forecast created_at reflects the latest write
When a stored forecast row for an existing (slot, version) is overwritten, its `created_at` SHALL be set to the time of the overwrite.

#### Scenario: Overwrite refreshes timestamp
- **WHEN** a forecast for an existing slot and version is stored again later
- **THEN** the row's `created_at` is later than the first insert time and the values are the new ones

#### Scenario: New row
- **WHEN** a forecast for a new slot is stored
- **THEN** `created_at` is the insert time
