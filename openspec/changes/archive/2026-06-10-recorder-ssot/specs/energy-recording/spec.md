## MODIFIED Requirements

### Requirement: HA History API Power-to-Energy Conversion
The system SHALL provide a generic function that fetches power sensor history from the HA History API for a given time window and computes energy by **time-weighted (step) integration** of the power samples over the window: `Σ powerᵢ · Δtᵢ`, where each sample's power is held constant from its `last_changed` timestamp until the next sample (zero-order hold), clipped to the requested `[start, end]` window. The function SHALL NOT use an unweighted sample mean.

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
- **THEN** the function SHALL exclude those samples, and hold the previous valid power across the excluded interval

### Requirement: Load Isolation from Deferrable Loads
Every writer of `slot_observations` — the live recorder AND the backfill/gap-fill path — SHALL subtract energy from controllable loads (EV charging, water heating) from the total load before storing `load_kwh`, so that `load_kwh` always represents base load only, with one consistent meaning regardless of which writer produced the row. The controllable-load energy used for the subtraction SHALL be the slot-aligned, integrated energy for that same completed slot (per the slot-alignment and integration requirements), falling back to the power snapshot only when history is unavailable.

#### Scenario: Live recorder subtracts EV charging energy from total load
- **WHEN** the live recorder calculates `total_load_kwh` as `5.0 kWh`
- **AND** EV charging consumed `2.0 kWh` during the same completed slot
- **THEN** the recorder SHALL store `3.0 kWh` as `load_kwh`

#### Scenario: Live recorder subtracts water heating energy from total load
- **WHEN** the live recorder calculates `total_load_kwh` as `4.0 kWh`
- **AND** water heating consumed `0.75 kWh` during the same completed slot
- **THEN** the recorder SHALL store `3.25 kWh` as `load_kwh`

#### Scenario: Backfill disaggregates exactly like the live path
- **WHEN** the backfill/gap-fill path fills a missing slot whose total load delta is `5.0 kWh`
- **AND** EV charging consumed `2.0 kWh` and water heating `0.5 kWh` during that slot (fetched from power history for the same window)
- **THEN** the backfill path SHALL store `2.5 kWh` as `load_kwh`, NOT the un-disaggregated `5.0 kWh`

#### Scenario: Base load never goes negative
- **WHEN** subtracting controllable-load energy would make `load_kwh` negative
- **THEN** the writer SHALL clamp `load_kwh` to `0.0`

## ADDED Requirements

### Requirement: Slot Alignment to Completed Window
The recorder SHALL record the 15-minute slot that has just **finished**, labeling the row with `slot_start = floor(now) − 15 minutes` and computing every field — cumulative-delta energy (load/PV/grid) and integrated controllable-load energy (EV/water) — over the single window `[slot_start, slot_start + 15 min]`. The `slot_start` label SHALL be derived from the wall-clock time, not from a loop iteration counter, so a late or skipped wake still labels the correct completed slot.

#### Scenario: Steady-state wake records the finished slot
- **WHEN** the recorder wakes at `12:15:04` (just after the boundary)
- **THEN** it SHALL record the slot labeled `slot_start = 12:00`
- **AND** all energy fields SHALL describe the window `[12:00, 12:15]`

#### Scenario: All fields align to one window
- **WHEN** the recorder records the `12:00` slot
- **THEN** the load/PV/grid deltas AND the EV/water integrated energy SHALL all cover `[12:00, 12:15]` — no field is shifted to a different slot

#### Scenario: Late wake still labels correctly
- **WHEN** the recorder wakes at `12:33` after missing the `12:15` boundary
- **THEN** it SHALL derive `slot_start` from the wall clock (the completed `12:15` slot) rather than assuming the previous iteration's slot

### Requirement: Correctable Energy Storage
The slot-observation UPSERT SHALL distinguish "no measurement available" (skip the column, keep any existing value) from "a real measurement" (write it). A real measurement from the authoritative live recorder SHALL be written even when it is lower than, or equal to zero relative to, the stored value, so over-counts can be corrected and genuine zeros can be stored. Non-authoritative backfill writes SHALL only fill columns that have no authoritative measurement yet and SHALL NOT overwrite an authoritative value.

#### Scenario: Live recorder corrects an over-counted value downward
- **WHEN** a slot already stores `pv_kwh = 8.0` from an earlier spike
- **AND** the live recorder re-records the same slot with a corrected `pv_kwh = 2.0`
- **THEN** the store SHALL overwrite the value to `2.0`

#### Scenario: True zero is stored
- **WHEN** the live recorder measures `ev_charging_kwh = 0.0` for a slot
- **THEN** the store SHALL persist `0.0` (not treat zero as "no data")

#### Scenario: Backfill does not wipe an authoritative value
- **WHEN** a slot already holds a live-recorded `load_kwh`
- **AND** backfill later processes the same slot
- **THEN** backfill SHALL leave the authoritative `load_kwh` unchanged

#### Scenario: Missing measurement keeps existing value
- **WHEN** a metric has no measurement for a slot (history unavailable and no snapshot)
- **THEN** the store SHALL keep any existing value for that column rather than overwriting it with a default

### Requirement: Canonical Column Ownership
Each `slot_observations` column SHALL have exactly one canonical owner. The recorder SHALL be the sole writer of the energy and price columns (including `load_kwh` as base load, `pv_kwh`, grid columns, `ev_charging_kwh`/`water_kwh` and their per-device JSON, and price columns). The executor SHALL be the sole writer of `executed_action`. No column SHALL be written by both owners.

#### Scenario: Recorder owns energy columns
- **WHEN** the executor records what it did for a slot
- **THEN** it SHALL write only `executed_action` (keyed on `slot_start`) and SHALL NOT write any energy or price column

#### Scenario: Executor write does not clobber recorder columns
- **WHEN** the executor updates `executed_action` for a slot the recorder also wrote
- **THEN** the recorder-owned energy/price columns for that slot SHALL be unaffected
