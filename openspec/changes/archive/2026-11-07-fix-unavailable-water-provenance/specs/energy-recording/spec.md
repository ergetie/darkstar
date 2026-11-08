# Spec Delta

## MODIFIED Requirements

### Requirement: HA History API Power-to-Energy Conversion
The system SHALL provide a generic function that fetches power sensor history from the HA History API for a given time window and computes energy by **time-weighted (step) integration** of the power samples over the window: `Σ powerᵢ · Δtᵢ`, where each sample's power is held constant from its `last_changed` timestamp until the next sample (zero-order hold), clipped to the requested `[start, end]` window. A state that is not a usable reading (`unavailable`, `unknown`, empty or non-numeric) SHALL end the hold at its timestamp: no power is held across the period until the next valid sample, and that period contributes no energy. The function SHALL NOT use an unweighted sample mean. When no valid interval overlaps the window the function SHALL return `None`.

#### Scenario: Step integration over irregular updates
- **WHEN** the function is called for `sensor.ev_power` from `03:00` to `03:15`
- **AND** the HA History API returns `0 kW` at `03:00` and a state change to `6.0 kW` at `03:10`
- **THEN** the function SHALL hold `0 kW` over `[03:00, 03:10)` and `6.0 kW` over `[03:10, 03:15]`
- **AND** return `0.5 kWh` (`0×10/60 + 6.0×5/60`), NOT the unweighted-mean result of `0.75 kWh`

#### Scenario: Single sample held across the window
- **WHEN** the function is called for `sensor.ev_power` from `03:00` to `03:15`
- **AND** the only sample is `4.0 kW` at `03:00` with no further state changes
- **THEN** the function SHALL return `1.0 kWh` (`4.0 × 0.25`)

#### Scenario: At-start state from before the window is clipped to the window
- **WHEN** the function is called from `03:00` to `03:15`
- **AND** the last state change before the window was `2.0 kW` at `02:58`
- **AND** a state change to `5.0 kW` occurs at `03:09`
- **THEN** the function SHALL integrate `2.0 kW` over `[03:00, 03:09)` and `5.0 kW` over `[03:09, 03:15]`
- **AND** return `0.8 kWh` (`2.0×9/60 + 5.0×6/60`)

#### Scenario: History API returns empty data
- **WHEN** the function is called for `sensor.ev_power` from `03:00` to `03:15`
- **AND** the HA History API returns an empty response or no valid data points
- **THEN** the function SHALL return `None`

#### Scenario: History API call fails
- **WHEN** the function is called and the HTTP request fails (timeout, connection error)
- **THEN** the function SHALL return `None`

#### Scenario: Power values require unit normalization
- **WHEN** the HA History API returns values in Watts (unit_of_measurement: "W")
- **THEN** the function SHALL normalize to kW before integrating

#### Scenario: Non-numeric and unavailable states are excluded
- **WHEN** the HA History API returns states including "unknown", "unavailable", or non-numeric values
- **THEN** the function SHALL treat each as a gap that ends the hold, and add no energy until the next valid sample

#### Scenario: Unavailable or unknown state ends the hold
- **WHEN** the HA History API returns `2.0 kW` at `03:00` and `unavailable` (or `unknown`) at `03:00:26`, for the window `03:00` to `03:15`
- **THEN** the function SHALL return about `0.0144 kWh` (`2.0 × 26/3600`), NOT `0.5 kWh`

#### Scenario: Sensor returns part-way through the window
- **WHEN** the window is `03:00` to `03:15`, the sensor is `unavailable` from `03:00` and reports `2.0 kW` at `03:10`
- **THEN** the function SHALL integrate `2.0 kW` over `[03:10, 03:15]` only and return `0.1667 kWh`

#### Scenario: Several interruptions in one window
- **WHEN** valid and unavailable periods alternate within the window
- **THEN** the function SHALL add only the valid periods, each held until the next state

#### Scenario: Window without a valid interval
- **WHEN** the sensor is unavailable for the whole window, or its first valid sample is after the window
- **THEN** the function SHALL return `None`

## ADDED Requirements

### Requirement: Every integration caller ignores unavailable periods alike
The recorder (every metric), backfill, the load profile, `get_energy_from_power_history` and the water heating progress SHALL integrate power history through the same gap-aware rule, with no per-metric exception. A slot whose water sensor is unavailable for only part of the slot SHALL stay `power_history`, and under `derived_history` its stored `load_kwh + water_kwh + ev_charging_kwh` SHALL equal the integrated total load.

#### Scenario: Water unavailable partway through a slot
- **GIVEN** a 2 kW water sensor valid for 26 s of a slot and then unavailable, and a constant 3 kW total load
- **WHEN** the recorder stores the slot
- **THEN** `water_kwh` is about 0.0144, the water component is `power_history`
- **AND** `load_kwh + water_kwh + ev_charging_kwh` equals 0.75 and the grid-only comparison includes the slot with grid-only cost `0.75 × price`

### Requirement: Unavailable water sensor keeps recorder-owned unknown provenance
When every water power source of a slot is unavailable (no history in the slot window and no usable snapshot), the recorder SHALL store the slot with `quality_flags.recording.components.water` set to method `unknown` and owner `recorder`, and SHALL NOT store a measured water value. The stored provenance SHALL NOT be replaced by an owner of `unknown` because the value is absent, whether the slot row is new or already exists.

#### Scenario: Fully unavailable water sensor, whole slot
- **GIVEN** the configured water sensor reports `unavailable` for a whole 15-minute slot and the load is derived from history
- **WHEN** the recorder stores the slot
- **THEN** the water component is method `unknown`, owner `recorder`
- **AND** the water energy is not recorded as measured
- **AND** the grid-only comparison includes the slot and counts it in `coverage.water_unmeasured_slots`

#### Scenario: Slot row already exists
- **GIVEN** a stored row for the slot whose water component has no metadata or `owner: unknown`
- **WHEN** the recorder stores the slot with an unavailable water sensor
- **THEN** the water component becomes method `unknown`, owner `recorder`

#### Scenario: Partly unavailable boundary slot
- **GIVEN** the water sensor becomes available again part-way through a slot, so history exists in the slot window
- **WHEN** the recorder stores the slot
- **THEN** the water component is method `power_history`, owner `recorder`, integrated over the valid part of the slot only
- **AND** the slot is eligible for the comparison without a water note

#### Scenario: Measured water is never downgraded
- **GIVEN** a stored slot whose water component is a measured method with a value
- **WHEN** a later recorder write for the same slot has every water source unavailable
- **THEN** the stored water value and its provenance are unchanged

#### Scenario: Guards still reject unsafe slots
- **GIVEN** a slot with recorder-owned `unknown` water
- **WHEN** the load method is `snapshot` or `mixed`, or `ev_charging_kwh` is above 0 with `load_kwh` equal to 0, or EV or load is `unknown`
- **THEN** the grid-only comparison excludes the slot

#### Scenario: Backfill still cannot overwrite recorder data
- **WHEN** a non-authoritative write targets a slot whose water component is owned by the recorder
- **THEN** the recorder's water value and provenance are kept

### Requirement: Backfill writes a slot only with measured core data
Backfill SHALL NOT write a slot observation unless every configured core energy metric (PV, load, grid import, grid export) has at least one valid history interval in that slot. A source that is not configured or is disabled records a real `0.0` and does not block the slot. Backfill SHALL NOT store a missing value as `0` for any of these NOT NULL columns, and SHALL leave nullable metrics (battery charge/discharge, SoC) NULL when they have no history. This does not change the recorder.

#### Scenario: Every sensor unavailable
- **GIVEN** every sensor reports `unavailable` for the whole backfill window
- **WHEN** backfill runs
- **THEN** no slot observation is written

#### Scenario: Partly unavailable day
- **GIVEN** the load sensor is unavailable for the first slots of the day and valid afterwards
- **WHEN** backfill runs
- **THEN** only the slots with a valid load interval are written, and no skipped slot exists as a row

#### Scenario: Configured PV sensor without history
- **GIVEN** the load is measured but the configured PV sensor has no valid interval in a slot
- **WHEN** backfill runs
- **THEN** that slot is not written, so `pv_kwh` is never stored as a fabricated 0

#### Scenario: Unmeasured water with measured core data
- **GIVEN** pv, load and grid are measured and the water sensor is unavailable for the slot
- **WHEN** backfill runs
- **THEN** the slot is written with water provenance `unknown`
