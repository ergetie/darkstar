# Spec Delta

## Purpose

Defines which stored learning data the planner and learning services may treat as learned, forecast or observed, so stale, wiped or fabricated values never drive planning, backfill or status displays.

## ADDED Requirements

### Requirement: No stored learned override of s_index.base_factor
The planner SHALL take `s_index.base_factor` only from configuration. It SHALL NOT read any learned or stored value that replaces it.

#### Scenario: Old metrics row exists
- **WHEN** `learning_daily_metrics` contains a row with `s_index_base_factor` 1.4066 and the configured `s_index.base_factor` is 1.1
- **THEN** the planner SHALL use 1.1

#### Scenario: Learning enabled or disabled
- **WHEN** `learning.enable` is true or false
- **THEN** planning SHALL read no value from `learning_daily_metrics`

### Requirement: Daily-metrics endpoint removed
The system SHALL NOT expose `GET /api/learning/daily_metrics`, because nothing writes the data it would serve.

#### Scenario: Route absent
- **WHEN** a client requests `GET /api/learning/daily_metrics`
- **THEN** the API SHALL respond 404

### Requirement: Forecast temperature survives re-upserts
Storing a forecast row without a temperature SHALL keep the temperature already stored for that slot and forecast version. A new non-null temperature SHALL replace it. A missing temperature SHALL remain NULL and never become 0.

#### Scenario: Planner re-upsert without temperature
- **WHEN** a forecast row with `temp_c` 1.5 is stored and the same slot is then stored with no `temp_c`
- **THEN** the stored `temp_c` SHALL still be 1.5

#### Scenario: New temperature
- **WHEN** a row with `temp_c` -2.0 is stored over a row with 1.5
- **THEN** the stored `temp_c` SHALL be -2.0

#### Scenario: Never measured
- **WHEN** a slot is stored with no `temp_c` and none was stored before
- **THEN** the stored `temp_c` SHALL be NULL

### Requirement: Last observation is the latest completed recorded slot
The last observation time SHALL be the start of the latest slot that has completed at the given time and holds recorder or backfill data (`quality_flags` set, or legacy `soc_end_percent` set). Price-only rows and slots still in progress or in the future SHALL NOT count. Ordering SHALL be by instant, not by timestamp text, across UTC offset changes.

#### Scenario: Future price rows
- **WHEN** the latest recorded slot is 3 hours before now and price-only rows exist for today and the next two days
- **THEN** the last observation time SHALL be that slot

#### Scenario: Only price rows
- **WHEN** `slot_observations` holds only price-only rows
- **THEN** the last observation time SHALL be none

#### Scenario: Slot in progress
- **WHEN** a recorded slot started 10 minutes before now
- **THEN** it SHALL NOT count, and the previous completed recorded slot SHALL be returned

#### Scenario: Price merged into a recorded slot
- **WHEN** prices are stored for a slot that already has recorder data
- **THEN** that slot SHALL still count once it has completed

#### Scenario: Autumn DST change
- **WHEN** recorded slots exist at `2026-10-25T02:30:00+02:00` and `2026-10-25T02:15:00+01:00`
- **THEN** the later instant (`02:15+01:00`) SHALL be returned as the latest

### Requirement: Backfill fills gaps despite stored future prices
The startup backfill SHALL measure its gap from the last completed recorded slot, so downtime gaps are backfilled even when future price rows are stored.

#### Scenario: Downtime gap with future prices stored
- **WHEN** the last recorded slot is 6 hours old and price rows exist for tomorrow
- **THEN** the backfill SHALL treat the gap as 6 hours and request history for the missing slots

### Requirement: No fabricated learning-loop status
The API SHALL NOT report per-loop status or last-run values that are not read from stored data.

#### Scenario: Loops endpoint removed
- **WHEN** a client requests `GET /api/learning/loops`
- **THEN** the API SHALL respond 404
