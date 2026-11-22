# Spec Delta

## MODIFIED Requirements

### Requirement: Load Isolation from Deferrable Loads
Every writer of `slot_observations` (live recorder and backfill) SHALL subtract controllable-load energy (EV charging, water heating) from the total load before storing `load_kwh`, so that it represents base load only. The subtracted energy SHALL be the integrated energy for that same completed slot, falling back to the power snapshot only when history is unavailable. A negative result SHALL be stored as an untrusted `0.0` placeholder and flagged (see `base-load-integrity`).

#### Scenario: Live recorder subtracts EV charging energy from total load
- **WHEN** the live recorder integrates total load as `5.0 kWh`
- **AND** EV charging consumed `2.0 kWh` during the same completed slot
- **THEN** the recorder SHALL store `3.0 kWh` as `load_kwh`

#### Scenario: Live recorder subtracts water heating energy from total load
- **WHEN** the live recorder integrates total load as `4.0 kWh`
- **AND** water heating consumed `0.75 kWh` during the same completed slot
- **THEN** the recorder SHALL store `3.25 kWh` as `load_kwh`

#### Scenario: Recorder subtracts both EV and water from total load
- **WHEN** the recorder integrates total load as `6.0 kWh`
- **AND** EV charging consumed `2.0 kWh`
- **AND** water heating consumed `0.75 kWh`
- **THEN** the recorder SHALL store `3.25 kWh` as `load_kwh`

#### Scenario: Base load never goes negative
- **WHEN** subtracting controllable-load energy would make `load_kwh` negative
- **THEN** the writer SHALL store `0.0`, log a warning, set `quality_flags.base_load.reliable` to false with reason `negative_after_subtraction`, and set the `load` component method to `unknown`

#### Scenario: Load snapshot fallback uses disaggregated base load
- **WHEN** power-history integration returns no value for `load_power`
- **AND** the LoadDisaggregator provides `base_load_kw` from power snapshot isolation
- **THEN** the recorder SHALL use `base_load_kw × 0.25` for `load_kwh` without subtracting EV and water a second time

#### Scenario: Backfill disaggregates exactly like the live path
- **WHEN** backfill integrates total load of `5.0 kWh` for a missing slot
- **AND** EV charging consumed `2.0 kWh` and water heating `0.5 kWh` during that slot
- **THEN** backfill SHALL store `2.5 kWh` as `load_kwh`

### Requirement: Consistent per-heater active-power normalization
The system SHALL apply each heater's finite non-negative `idle_power_threshold_kw` after power-unit conversion and before integrating energy, using the larger of that value and a built-in noise floor of 0.010 kW. Samples below the effective cutoff SHALL contribute zero active-heating power; samples at or above it SHALL retain their normalized power. The configured default stays 0, so a configured cutoff of 0 still removes sensor noise below 10 W but nothing above.

#### Scenario: Same rule on all paths
- **WHEN** history integration, snapshot fallback, backfill, recent planner progress, live load disaggregation or heating activity detection evaluates heater power
- **THEN** each uses the same effective cutoff

#### Scenario: Noise below the floor with cutoff 0
- **WHEN** a heater with cutoff 0 reports 0.001 kW or 0.002 kW for a whole slot
- **THEN** its active water energy SHALL be zero and the slot has no tiny positive water value

#### Scenario: Floor boundary
- **WHEN** a heater with cutoff 0 reports 10 W or 0.010 kW
- **THEN** the sample is retained, and 9 W contributes zero

#### Scenario: Larger configured cutoff wins
- **WHEN** the configured cutoff is 0.10 kW
- **THEN** the effective cutoff is 0.10 kW and the existing idle, mixed-slot and boundary behaviours hold

#### Scenario: Idle draw is household consumption
- **WHEN** a heater draws 0.06 kW throughout a 15-minute slot with cutoff 0.10 kW
- **THEN** its active water energy SHALL be zero
- **AND** the 0.015 kWh idle consumption SHALL remain in base load
- **AND** it SHALL NOT be detected as actively heating

#### Scenario: Mixed slot is filtered before integration
- **WHEN** valid heater samples indicate 3 kW for 10 minutes and 0.06 kW for 5 minutes with cutoff 0.10 kW
- **THEN** active water energy SHALL be 0.50 kWh, not the integral of idle draw and not a threshold applied to slot-average power
- **AND** load isolation SHALL subtract 0.50 kWh exactly once

#### Scenario: Unit conversion and boundary are consistent
- **WHEN** a sensor reports 100 W or 0.10 kW with cutoff 0.10 kW
- **THEN** both SHALL retain 0.10 kW active power
- **AND** a 99 W sample SHALL contribute zero

#### Scenario: Filtered energy and base load
- **WHEN** water energy is filtered by the effective cutoff
- **THEN** the filtered water energy is subtracted from total load
- **AND** excluded idle consumption remains in household base load
- **AND** metered grid energy is unchanged

#### Scenario: Fallback and backfill match live recording
- **WHEN** live history, snapshot fallback, backfill or recent progress handles the same normalized samples and configured cutoff
- **THEN** they SHALL classify idle and active power consistently and retain truthful measurement provenance

## ADDED Requirements

### Requirement: Device history coverage and inactive-device power are recorded
The recorder and backfill SHALL compute, per enabled water heater and EV charger and for the total-load sensor, the share of the slot covered by valid history, and SHALL flag the slot when that share is below 0.95. Sensors of devices excluded by configuration SHALL be read too, and their non-zero active energy SHALL flag the slot while the device stays `disabled_zero` with value 0.

#### Scenario: Flag reasons by source
- **WHEN** a device share is below 0.95
- **THEN** the reason is `device_partial_coverage` and the device method and value are unchanged
- **WHEN** the total-load share is below 0.95
- **THEN** the reason is `load_partial_coverage` and the `load` method becomes `unknown`
- **WHEN** an excluded device sensor shows non-zero active energy
- **THEN** the reason is `inactive_device_drawing_power`

#### Scenario: Heater sensor missing the first third of a slot
- **WHEN** the heater sensor has valid history only for the last 10 minutes of a 15-minute slot
- **THEN** its energy is the integrated 10 minutes, its method is `power_history`, and the slot is flagged `device_partial_coverage`

#### Scenario: Total load sensor missing part of a slot
- **WHEN** `load_power` has valid history for only 10 of 15 minutes
- **THEN** the slot is flagged `load_partial_coverage` and `load_kwh` is not trusted as base load

#### Scenario: Slot boundary shorter than the tolerance
- **WHEN** valid history covers at least 95 percent of the slot
- **THEN** the slot is not flagged

#### Scenario: Excluded heater with a live sensor
- **WHEN** `has_water_heater` is false and the configured heater sensor reads 2 kW for the slot
- **THEN** water is `disabled_zero` 0, the slot is flagged `inactive_device_drawing_power` and a warning is logged once for that sensor

#### Scenario: Excluded heater sensor unavailable
- **WHEN** the excluded sensor has no history
- **THEN** the slot is not flagged and no value is fabricated
