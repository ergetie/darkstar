## Purpose

TBD - Energy recording capability for accurate historical energy tracking using cumulative meter sensors.

## Requirements

### Requirement: Support for Cumulative Energy Sensors
The system SHALL support configuring cumulative energy sensors (meter readings) in `input_sensors` for PV, Load, Grid, and Battery. These sensors represent total energy processed over the device's lifetime.

#### Scenario: User configures a total PV production sensor
- **WHEN** the user adds `total_pv_production: sensor.pv_energy_total` to `input_sensors` in `config.yaml`
- **THEN** the system SHALL recognize this as a cumulative source for PV energy calculation

### Requirement: Delta-based Energy Calculation
The recorder SHALL calculate the energy for a 15-minute slot by subtracting the cumulative meter reading at the start of the slot from the reading at the end of the slot, then scaling the result proportionally to represent exactly 15 minutes of energy when the sensor's update timing differs from the recording interval.

#### Scenario: Recorder calculates energy during a continuous run
- **WHEN** the recorder has a previous reading of `1000.0 kWh` for PV at `12:00`
- **AND** the current reading at `12:15` is `1001.2 kWh`
- **THEN** the recorder SHALL store `1.2 kWh` as the `pv_kwh` for the `12:00` slot

#### Scenario: Recorder calculates energy with matching timing
- **WHEN** the recorder has a previous reading of `1000.0 kWh` for PV at `12:00`
- **AND** the current reading at `12:15` is `1001.2 kWh`
- **AND** the sensor's `last_updated` timestamp indicates exactly 15 minutes elapsed
- **THEN** the recorder SHALL store `1.2 kWh` as the `pv_kwh` for the `12:00` slot

#### Scenario: Recorder scales energy when timing differs
- **WHEN** the recorder reads PV cumulative `1000.0 kWh` at `11:00:05` with sensor timestamp `10:53`
- **AND** the previous reading was `998.0 kWh` with sensor timestamp `10:43`
- **AND** the raw delta is `2.0 kWh` over 10 actual minutes
- **THEN** the recorder SHALL scale to `3.0 kWh` (2.0 × 15/10) for the 15-minute slot

#### Scenario: Recorder handles missing sensor timestamp gracefully
- **WHEN** the sensor's `last_updated` field is unavailable
- **THEN** the recorder SHALL use the raw delta without scaling

#### Scenario: Recorder skips scaling for extreme time gaps
- **WHEN** the time between sensor timestamps is less than 5 minutes or greater than 60 minutes
- **THEN** the recorder SHALL use the raw delta without scaling

### Requirement: Persistent Recorder State
The recorder SHALL persist its last known meter readings to a local state file to allow accurate delta calculation across service restarts.

#### Scenario: Recorder resumes after a restart
- **WHEN** the recorder service starts up
- **AND** it finds a state file containing a PV reading of `500.0 kWh` from 15 minutes ago
- **AND** the current HA reading is `500.5 kWh`
- **THEN** it SHALL record `0.5 kWh` for the missing slot instead of defaulting to 0 or snapshots

### Requirement: Automatic Unit Normalization
The system SHALL automatically normalize cumulative energy sensor values to kWh, supporting Wh, kWh, and MWh units based on the sensor's `unit_of_measurement` attribute. When no unit is specified, the system SHALL use a magnitude-based heuristic to detect Wh values and convert accordingly.

#### Scenario: Sensor reports in Watt-hours
- **WHEN** a cumulative sensor reports `500000` with `unit_of_measurement: "Wh"`
- **THEN** the system SHALL normalize to `500.0 kWh`
- **AND** delta calculations SHALL use the normalized value

#### Scenario: Sensor reports in kilowatt-hours
- **WHEN** a cumulative sensor reports `500.0` with `unit_of_measurement: "kWh"`
- **THEN** the system SHALL use the value as-is

#### Scenario: Sensor reports in megawatt-hours
- **WHEN** a cumulative sensor reports `0.5` with `unit_of_measurement: "MWh"`
- **THEN** the system SHALL normalize to `500.0 kWh`

#### Scenario: Sensor reports in Wh with non-standard unit string
- **WHEN** a cumulative sensor reports `5675983` with `unit_of_measurement: "W·h"` or `"W h"` or `"watthour"` or any case variant of Wh
- **THEN** the system SHALL normalize to `5675.983 kWh`

#### Scenario: Sensor reports large value with no unit attribute
- **WHEN** a cumulative sensor reports `5675983` with no `unit_of_measurement` attribute (None or missing)
- **AND** the value exceeds the Wh detection threshold (default 100,000)
- **THEN** the system SHALL assume Wh and normalize to `5675.983 kWh`
- **AND** the system SHALL log an info message: "Energy normalization: X (no unit) → Y kWh (Wh inferred from magnitude)"

#### Scenario: Sensor reports small value with no unit attribute
- **WHEN** a cumulative sensor reports `500.0` with no `unit_of_measurement` attribute
- **AND** the value is at or below the Wh detection threshold
- **THEN** the system SHALL assume kWh and use `500.0` as-is

### Requirement: Unit Propagation in History Processing

The `get_load_profile_from_ha` function SHALL propagate the `unit_of_measurement` from the first HA history state entry to all subsequent entries that lack attributes. The HA history API only includes attributes on the first entry in a response series — the function MUST NOT rely on every state entry having its own `unit_of_measurement`.

#### Scenario: HA history returns attributes only on first entry
- **WHEN** the first state entry has `attributes: {"unit_of_measurement": "Wh"}` and all subsequent entries have `attributes: {}`
- **THEN** the function SHALL apply the `"Wh"` unit to ALL state entries when normalizing
- **AND** all cumulative values SHALL be consistently divided by 1000

#### Scenario: No state entry has attributes
- **WHEN** all state entries have `attributes: {}` (no `unit_of_measurement` anywhere)
- **THEN** the function SHALL pass `None` as the unit to normalization
- **AND** the magnitude-based heuristic SHALL apply as fallback

#### Scenario: Unit changes mid-series
- **WHEN** a later state entry introduces a different `unit_of_measurement` (e.g., sensor reconfigured)
- **THEN** the function SHALL adopt the new unit from that entry onward

### Requirement: Load Profile Sanity Bound
The `get_load_profile_from_ha` function SHALL validate the computed daily total before returning. If the daily total exceeds a reasonable residential threshold, the function SHALL discard the profile and return the dummy fallback.

#### Scenario: Normal daily total passes validation
- **WHEN** `get_load_profile_from_ha` computes a daily total of `25.0 kWh/day`
- **THEN** the function SHALL return the computed profile normally

#### Scenario: Absurd daily total triggers fallback
- **WHEN** `get_load_profile_from_ha` computes a daily total exceeding `500 kWh/day`
- **THEN** the function SHALL log a warning with the computed total and entity ID
- **AND** the function SHALL return the dummy load profile instead

### Requirement: Unit Detection Logging
The normalization function SHALL log the detected unit and conversion result at debug level for every cumulative sensor read, enabling diagnosis of sensor configuration issues.

#### Scenario: Unit detected from attribute
- **WHEN** the normalization function processes a value of `500000` with `unit_of_measurement: "Wh"`
- **THEN** the function SHALL log at debug level: "Energy normalization: 500000 Wh → 500.0 kWh (from unit_of_measurement)"

#### Scenario: Unit inferred from magnitude
- **WHEN** the normalization function processes a value of `5675983` with no `unit_of_measurement`
- **THEN** the function SHALL log at info level: "Energy normalization: 5675983 (no unit) → 5675.983 kWh (Wh inferred from magnitude)"

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

### Requirement: EV Energy Recording via Power History
The recorder SHALL calculate EV charging energy for each slot per-device by fetching each enabled charger's power sensor history over the slot window. The recorder SHALL store both aggregate `ev_charging_kwh` (sum across all chargers) and per-device energy in the slot observation.

#### Scenario: Single EV charger recording unchanged
- **WHEN** one enabled EV charger has `sensor: sensor.ev_power` configured
- **THEN** the recorder SHALL call the power history function for the slot window
- **AND** store the result as `ev_charging_kwh`

#### Scenario: Multiple EV chargers with per-device tracking
- **WHEN** two enabled EV chargers are configured (charger A: 2.0 kWh, charger B: 1.5 kWh)
- **THEN** the recorder SHALL store `ev_charging_kwh = 3.5` (aggregate)
- **AND** the recorder SHALL store per-device energy keyed by charger ID

#### Scenario: EV history API fallback to power snapshot
- **WHEN** the power history function returns `None` for an EV charger
- **THEN** the recorder SHALL fall back to `current_power_kw * 0.25` using the point-in-time power reading for that specific charger

### Requirement: Per-device EV energy storage
The recorder SHALL store per-device EV energy in the slot observation metadata or as a JSON field, keyed by charger ID. This enables future per-device analytics without requiring schema changes per charger.

#### Scenario: Per-device energy stored as JSON
- **WHEN** the recorder stores a slot observation with two active EV chargers
- **THEN** the observation SHALL include a field (e.g., `ev_charger_energy`) containing `{"ev_charger_1": 2.0, "ev_charger_2": 1.5}`

#### Scenario: Single charger backward compatible
- **WHEN** only one charger is active
- **THEN** `ev_charging_kwh` SHALL contain the total (same as before)
- **AND** `ev_charger_energy` SHALL contain `{"ev_charger_1": 2.0}`

#### Scenario: No active chargers
- **WHEN** no EV chargers are enabled or none are charging
- **THEN** `ev_charging_kwh` SHALL be `0.0`
- **AND** `ev_charger_energy` SHALL be `{}` or omitted

### Requirement: Water Heater Energy Recording via Power History
The recorder SHALL calculate water heater energy for each slot per-device by fetching each enabled heater's power sensor history over the slot window. The recorder SHALL store both aggregate `water_kwh` (sum across all heaters) and per-device energy in the slot observation.

#### Scenario: Single water heater recording unchanged
- **WHEN** one enabled water heater has `sensor: sensor.wh_power` configured
- **THEN** the recorder SHALL call the power history function for the slot window
- **AND** store the result as `water_kwh`

#### Scenario: Multiple water heaters with per-device tracking
- **WHEN** two enabled water heaters are configured (heater A: 0.75 kWh, heater B: 0.50 kWh)
- **THEN** the recorder SHALL store `water_kwh = 1.25` (aggregate)
- **AND** the recorder SHALL store per-device energy keyed by heater ID

#### Scenario: Water heater history API fallback to power snapshot
- **WHEN** the power history function returns `None` for a water heater
- **THEN** the recorder SHALL fall back to `current_power_kw * 0.25` using the point-in-time power reading for that specific heater

### Requirement: Per-device water energy storage
The recorder SHALL store per-device water energy in the slot observation metadata or as a JSON field, keyed by heater ID. This enables future per-device analytics without requiring schema changes per heater.

#### Scenario: Per-device energy stored as JSON
- **WHEN** the recorder stores a slot observation with two active water heaters
- **THEN** the observation SHALL include a field (e.g., `water_heater_energy`) containing `{"main_tank": 0.75, "upstairs_tank": 0.50}`

#### Scenario: Single heater backward compatible
- **WHEN** only one heater is active
- **THEN** `water_kwh` SHALL contain the total (same as before)
- **AND** `water_heater_energy` SHALL contain `{"main_tank": 0.75}`

#### Scenario: No active heaters
- **WHEN** no water heaters are enabled or none are heating
- **THEN** `water_kwh` SHALL be `0.0`
- **AND** `water_heater_energy` SHALL be `{}` or omitted

### Requirement: Generic Function Robustness
The power history function SHALL be production-grade: it SHALL use a reasonable HTTP timeout (10-15s), SHALL return `None` on any failure without raising exceptions, and SHALL log failures at warning level. The function SHALL NOT implement its own retry logic — retry is handled at the recorder service layer.

#### Scenario: HTTP timeout
- **WHEN** the HA History API does not respond within the timeout
- **THEN** the function SHALL return `None`
- **AND** log a warning with the entity ID and error

#### Scenario: Connection error
- **WHEN** the HTTP connection to HA fails
- **THEN** the function SHALL return `None`
- **AND** log a warning with the entity ID and error

#### Scenario: Unexpected exception
- **WHEN** any unexpected error occurs during processing
- **THEN** the function SHALL catch the exception, return `None`, and log a warning

### Requirement: Snapshot Fallback
The recorder SHALL fall back to power-snapshot based estimation (kW × 0.25h) when the HA History API power-to-energy function returns `None` for a specific metric.

#### Scenario: Missing total energy sensor
- **WHEN** `input_sensors` only contains `pv_power: sensor.pv_current_kw` (no total energy sensor)
- **THEN** the recorder SHALL continue to use `pv_power * 0.25` to estimate energy for the slot

#### Scenario: History API unavailable for EV
- **WHEN** the power history function returns `None` for an EV charger power sensor
- **THEN** the recorder SHALL use `ev_power_kw × 0.25` to estimate energy for the slot

#### Scenario: History API unavailable for water heater
- **WHEN** the power history function returns `None` for a water heater power sensor
- **THEN** the recorder SHALL use `water_power_kw × 0.25` to estimate energy for the slot

#### Scenario: PV/load/grid unchanged
- **WHEN** the recorder calculates PV, load, or grid energy
- **THEN** the recorder SHALL continue using cumulative energy sensor deltas as the primary method
- **AND** fall back to power snapshot only when no cumulative sensor is configured

### Requirement: Energy value validation before storage
The recorder SHALL validate all energy values against physical limits before storing to `slot_observations`.

#### Scenario: Valid energy values stored
- **WHEN** all energy values in a record are within the calculated `max_kwh_per_slot`
- **THEN** the recorder SHALL store the values unchanged

#### Scenario: Spike values zeroed before storage
- **WHEN** an energy value exceeds `max_kwh_per_slot`
- **THEN** the recorder SHALL set that value to `0.0` before storage
- **AND** the recorder SHALL log a warning identifying the spiked field

### Requirement: Backfill uses config-derived threshold
The learning engine's `etl_cumulative_to_slots` and `etl_power_to_slots` functions SHALL use the config-derived threshold for spike filtering instead of a hardcoded value.

#### Scenario: Backfill filters spikes using config threshold
- **WHEN** backfill processes cumulative or power sensor data
- **AND** a delta exceeds `max_kwh_per_slot`
- **THEN** the delta SHALL be set to `0.0`

### Requirement: Analytical pipelines filter spike rows at read time
All analytical read paths that consume `pv_kwh` or `load_kwh` from `slot_observations` SHALL exclude rows where those values exceed `max_kwh_per_slot`.

#### Scenario: Analyst bias calculation excludes spike rows
- **WHEN** `Analyst._fetch_observations` fetches rows for bias analysis
- **THEN** rows where `load_kwh` or `pv_kwh` exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: Reflex accuracy analysis excludes spike rows
- **WHEN** `LearningStore.get_forecast_vs_actual` returns rows for Reflex
- **THEN** rows where the actual energy column exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: MAE metrics exclude spike rows
- **WHEN** `LearningStore.calculate_metrics` computes forecast MAE
- **THEN** the query SHALL exclude rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot`

#### Scenario: ML model training excludes spike rows
- **WHEN** `ml/train.py` `_load_slot_observations` loads data for Aurora model training
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded from training data

#### Scenario: ML error correction training excludes spike rows
- **WHEN** `ml/corrector.py` `_load_training_frame` loads data for error correction model training
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded

#### Scenario: ML evaluation metrics exclude spike rows
- **WHEN** `ml/evaluate.py` `_compute_mae` calculates forecast accuracy metrics
- **THEN** rows where `pv_kwh` or `load_kwh` exceeds `max_kwh_per_slot` SHALL be excluded from MAE calculation

### Requirement: Persistent Sensor Timestamp Storage
The recorder SHALL store the sensor's `last_updated` timestamp alongside each cumulative meter reading in the state file to enable time-proportional scaling on subsequent recordings.

#### Scenario: State file includes sensor timestamp
- **WHEN** the recorder successfully reads a cumulative sensor value
- **THEN** the state file entry SHALL include `sensor_timestamp` with the ISO format timestamp from the sensor's `last_updated` field

#### Scenario: Backward compatible with old state files
- **WHEN** the recorder reads a state file entry without `sensor_timestamp`
- **THEN** the recorder SHALL proceed without scaling for that recording cycle

### Requirement: Backfill Interpolation for Cumulative Sensors
The learning engine's `etl_cumulative_to_slots` function SHALL use linear interpolation to estimate cumulative values at exact slot boundaries, ensuring consistent delta calculations across all slots.

#### Scenario: Backfill interpolates to slot boundaries
- **WHEN** backfill processes cumulative sensor data with readings at irregular times
- **THEN** the function SHALL interpolate cumulative values at `:00, :15, :30, :45` boundaries
- **AND** delta calculations SHALL use these interpolated boundary values

#### Scenario: Backfill handles edge cases with fill
- **WHEN** interpolation leaves NaN values at series edges
- **THEN** the function SHALL apply forward-fill then backward-fill to ensure complete coverage

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

#### Scenario: Recorder subtracts both EV and water from total load
- **WHEN** the recorder calculates `total_load_kwh` as `6.0 kWh`
- **AND** EV charging consumed `2.0 kWh`
- **AND** water heating consumed `0.75 kWh`
- **THEN** the recorder SHALL store `3.25 kWh` as `load_kwh`

#### Scenario: Base load never goes negative
- **WHEN** subtracting controllable-load energy would make `load_kwh` negative
- **THEN** the writer SHALL clamp `load_kwh` to `0.0`

#### Scenario: Load isolation always applies
- **WHEN** EV or water energy is calculated via power history or snapshot fallback
- **THEN** the recorder SHALL always subtract those values from total load
- **AND** isolation SHALL NOT be conditional on any sensor type configuration

#### Scenario: Recorder uses power snapshot fallback when no cumulative sensor
- **WHEN** no `total_load_consumption` sensor is configured
- **AND** the LoadDisaggregator provides `base_load_kw` from power snapshot isolation
- **THEN** the recorder SHALL use `base_load_kw * 0.25` for `load_kwh`

#### Scenario: Backfill disaggregates exactly like the live path
- **WHEN** the backfill/gap-fill path fills a missing slot whose total load delta is `5.0 kWh`
- **AND** EV charging consumed `2.0 kWh` and water heating `0.5 kWh` during that slot (fetched from power history for the same window)
- **THEN** the backfill path SHALL store `2.5 kWh` as `load_kwh`, NOT the un-disaggregated `5.0 kWh`

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
