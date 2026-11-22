# Spec Delta

## Purpose
Defines when a stored `load_kwh` may be trusted as base load, how untrustworthy slots are marked without a schema change, and which consumers must skip them, so no model or benchmark learns from a fake or contaminated base load.

## ADDED Requirements

### Requirement: Unreliable base load is flagged, never trusted silently
Every writer of `slot_observations` SHALL record `quality_flags.base_load` as `{"reliable": false, "reasons": [...]}` when the stored `load_kwh` is not a trustworthy base load. A reliable slot SHALL carry no `base_load` key, and `load_kwh` SHALL keep a numeric value without any schema change.

#### Scenario: Flag shape and reasons
- **WHEN** a slot is flagged
- **THEN** each reason is one of `negative_after_subtraction`, `device_partial_coverage`, `load_partial_coverage`, `inactive_device_drawing_power`, `legacy_counter_clamp`, `legacy_counter_after_clamp` or `device_disabled_but_configured`
- **AND** `load_kwh` holds a numeric value (0 placeholder when the subtraction went negative)

#### Scenario: Subtraction goes negative
- **WHEN** total load is 0.20 kWh and water plus EV energy of the same slot is 0.75 kWh
- **THEN** the slot is stored with `base_load.reliable` false and reason `negative_after_subtraction`
- **AND** the `load` component method is `unknown`
- **AND** the clamp is logged once per slot

#### Scenario: Exactly zero base load is not a clamp
- **WHEN** total load equals water plus EV energy
- **THEN** `load_kwh` is 0 and the slot is not flagged

#### Scenario: Partial device coverage
- **WHEN** a water or EV sensor has valid history for less than the minimum coverage share (0.95) of the slot
- **THEN** the slot is flagged with reason `device_partial_coverage`
- **AND** the device component method stays `power_history` and its energy is kept

#### Scenario: Partial total-load coverage
- **WHEN** the `load_power` sensor has valid history for less than the minimum coverage share of the slot
- **THEN** the slot is flagged with reason `load_partial_coverage` and the `load` component method is `unknown`, because the derived load and demand are understated

#### Scenario: Full coverage is not flagged
- **WHEN** every device sensor and the load sensor have valid history for at least the minimum coverage share
- **THEN** no `base_load` flag is written

#### Scenario: Unavailable device sensor
- **WHEN** a water or EV sensor has no history and no snapshot for the slot
- **THEN** its component method is `unknown` and the slot is excluded from base-load consumers through the existing device-unknown rule, without a second `base_load` flag

#### Scenario: Disabled device still draws power
- **WHEN** a heater or charger is excluded by configuration (`has_water_heater` false, `has_ev_charger` false or `enabled` false) but its configured power sensor shows non-zero active energy in the slot
- **THEN** the device component stays `disabled_zero` with value 0
- **AND** the slot is flagged with reason `inactive_device_drawing_power`
- **AND** one warning per sensor and process names the sensor and the configuration keys to check

#### Scenario: Disabled device idle
- **WHEN** such a sensor shows no active energy in the slot
- **THEN** the slot is not flagged

#### Scenario: Backfill matches live recording
- **WHEN** backfill writes a slot with the same inputs
- **THEN** it applies the same flagging rules as the live recorder

#### Scenario: Cumulative counters stay out
- **THEN** total load is only ever integrated from the power history of `load_power`, never from a cumulative energy counter

### Requirement: Flagged slots are skipped by every base-load consumer
A slot with `base_load.reliable == false` SHALL be treated as an unmeasured base load wherever the existing unmeasured-device rule applies, in equivalent Python and SQL forms and including rows without `recording` provenance. Display consumers SHALL show no actual load for a flagged slot.

#### Scenario: Demand-affecting reasons
- **WHEN** a flag carries `negative_after_subtraction`, `load_partial_coverage`, `legacy_counter_clamp` or `legacy_counter_after_clamp`
- **THEN** the slot is also excluded from demand-based consumers (grid-only comparison, battery benchmark, calibration)

#### Scenario: Load training
- **WHEN** load training selects observations
- **THEN** flagged slots are dropped and counted in `dropped_unmeasured_device_rows`

#### Scenario: Load profile and accuracy metrics
- **WHEN** the base-load average, graduation level, forecast MAE or correction statistics read `load_kwh`
- **THEN** flagged slots are excluded

#### Scenario: Partial coverage keeps demand usable
- **WHEN** a slot is flagged only `device_partial_coverage`
- **THEN** grid-only comparison and benchmark still use its recorded demand (load plus water plus EV), because the derived load still contains the uncovered device energy

#### Scenario: Clamp hides demand
- **WHEN** a slot is flagged `negative_after_subtraction`
- **THEN** grid-only comparison, benchmark and calibration exclude it

#### Scenario: Chart actuals
- **WHEN** the forecast or schedule API returns actual load for a flagged slot
- **THEN** the value is null

### Requirement: Historical rows are flagged by an idempotent one-time migration
A one-time data migration SHALL set `quality_flags.base_load` on existing rows without changing any column value or schema. It SHALL preserve existing flag content, be idempotent, record its completion so it runs once, and log the number of rows flagged per rule.

#### Scenario: Migration rules
- **WHEN** the migration runs
- **THEN** rule (a) gives rows without `quality_flags.recording` (the marker of rows written by the current recorder or backfill) with `load_kwh = 0` and `water_kwh > 0` the reason `legacy_counter_clamp`, and the immediately following slot of each such row `legacy_counter_after_clamp`, whatever the installation's upgrade date
- **AND** rule (b) gives rows whose water component is `disabled_zero` the reason `device_disabled_but_configured` while the current configuration lists a water heater with a power sensor

#### Scenario: Old-era clamp row
- **GIVEN** a row without `recording` provenance with `load_kwh` 0 and `water_kwh` 0.75
- **WHEN** the migration runs
- **THEN** it has `base_load.reliable` false with reason `legacy_counter_clamp`
- **AND** the next slot has reason `legacy_counter_after_clamp`

#### Scenario: Row with recording provenance untouched by rule (a)
- **GIVEN** a row with `recording` provenance, `load_kwh` 0 and `water_kwh` 0.75
- **THEN** the migration does not flag it for reason (a)

#### Scenario: Installation upgraded late
- **GIVEN** an installation whose old-recorder rows extend to any date
- **THEN** rule (a) selects them by the missing `recording` key alone, with no date comparison

#### Scenario: Counts logged
- **WHEN** the migration finishes
- **THEN** it logs how many rows each rule flagged (a, after-clamp, b)

#### Scenario: Disabled but configured
- **GIVEN** rows with water `disabled_zero` and a configured heater sensor in the current configuration
- **WHEN** the migration runs
- **THEN** they are flagged `device_disabled_but_configured`

#### Scenario: No configured sensor
- **GIVEN** no water heater with a power sensor in the configuration
- **THEN** (b) flags nothing

#### Scenario: Idempotent and preserving
- **WHEN** the migration runs twice, or on a row with existing `recording` and `water_heater_energy` flags
- **THEN** the second run changes no row and existing flag keys are unchanged

#### Scenario: Malformed flags
- **WHEN** a row has NULL or unparseable `quality_flags`
- **THEN** the migration creates a valid object containing only `base_load` (NULL) or leaves the row untouched and logs it (unparseable)
