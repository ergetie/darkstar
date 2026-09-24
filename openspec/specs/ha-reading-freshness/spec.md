## Purpose

Defines how Darkstar determines the age of a live Home Assistant sensor reading, so that staleness checks treat a sensor that keeps reporting an unchanged value as fresh.

## Requirements

### Requirement: Reading freshness timestamp
Whenever Darkstar judges the age of a live Home Assistant sensor reading (a single current state, not a history series), it SHALL use the entity's `last_reported` timestamp. If `last_reported` is absent or unparseable it SHALL fall back to `last_updated`, then `last_changed`. If none is parseable the reading SHALL be treated as having no known timestamp. Parsed timestamps SHALL be timezone-aware (naive values interpreted as UTC). This logic SHALL live in one shared helper used by all freshness consumers.

#### Scenario: Unchanged value re-reported
- **WHEN** a sensor's value has been constant for 60 s but HA received a report 5 s ago (`last_reported` 5 s old, `last_updated` 60 s old)
- **THEN** the reading's age SHALL be 5 s

#### Scenario: Older HA without last_reported
- **WHEN** the state has no `last_reported` but has `last_updated`
- **THEN** the reading's age SHALL be derived from `last_updated`

#### Scenario: No usable timestamp
- **WHEN** none of `last_reported`, `last_updated`, `last_changed` is present or parseable
- **THEN** the helper SHALL return no timestamp and consumers SHALL treat the reading as of unknown age

#### Scenario: History consumers unaffected
- **WHEN** code processes an HA history series (ML features, history import, energy recorder scaling)
- **THEN** it SHALL continue to use value-change time and SHALL NOT use this helper
