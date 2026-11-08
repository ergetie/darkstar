## Purpose

Records accurate historical energy per slot by step-integrating power sensor history from Home Assistant, and keeps the stored observations correctable and traceable to their measurement source.

## Requirements
### Requirement: Load Profile Sanity Bound
The `get_load_profile_from_ha` function SHALL build the 7-day load profile by step-integrating `input_sensors.load_power` history and SHALL validate the computed daily total before returning. If the daily total exceeds a reasonable residential threshold, the function SHALL discard the profile and use the fallback profile.

#### Scenario: Normal daily total passes validation
- **WHEN** `get_load_profile_from_ha` computes a daily total of `25.0 kWh/day`
- **THEN** the function SHALL return the computed profile normally

#### Scenario: Absurd daily total triggers fallback
- **WHEN** `get_load_profile_from_ha` computes a daily total exceeding `500 kWh/day`
- **THEN** the function SHALL log a warning with the computed total and entity ID
- **AND** the function SHALL return the fallback load profile instead

#### Scenario: Profile is built from load power
- **WHEN** `load_power` reports a constant `1.0 kW` over the 7-day window
- **THEN** every slot of the profile SHALL be `0.25 kWh` and the daily total `24 kWh`

### Requirement: Load Profile Averages Over Measured Time
The 7-day load profile SHALL average each of the 96 local time-of-day slots only over the time it had a valid reading: summed energy divided by covered duration, scaled to the 15-minute slot length. A sensor outage SHALL NOT count as zero load. Slots without enough valid data SHALL be interpolated, or the profile discarded when too few slots have data.

#### Scenario: Whole-slot outage on one day
- **WHEN** `load_power` is unavailable for 6 h on one of the 7 days and every other day has valid data for those slots
- **THEN** the profile for those slots SHALL equal the mean of the other days, not 6/7 of it

#### Scenario: Partial-slot outage
- **WHEN** a slot has valid data for 6 full days and 5 of its 15 minutes on a seventh day
- **THEN** its value SHALL be the energy measured in it divided by `6 x 900 + 300` seconds, times 900 s

#### Scenario: Fully covered window is unchanged
- **WHEN** every slot has valid data on every day
- **THEN** the profile SHALL equal the energy summed per slot divided by 7, as before

#### Scenario: Slot never measured
- **WHEN** a slot has less than 15 minutes of valid data over the whole window but enough slots around it do
- **THEN** its value SHALL be interpolated linearly between the nearest measured slots before and after it, wrapping over midnight

#### Scenario: Too little measured data
- **WHEN** fewer than 48 of the 96 slots have at least 15 minutes of valid data
- **THEN** the fallback profile SHALL be returned and the degraded message SHALL name the sensor and the number of slots with data

### Requirement: HA History API Power-to-Energy Conversion
The system SHALL provide a generic function that fetches power sensor history from the HA History API and computes energy by **time-weighted (step) integration** `Σ powerᵢ · Δtᵢ`, each sample held until the next and clipped to `[start, end]`. A state that is not a usable reading (`unavailable`, `unknown`, empty, non-numeric) SHALL end the hold and add no energy. It SHALL NOT use an unweighted mean, and SHALL return `None` when no valid interval overlaps the window.

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

### Requirement: Unit Propagation in Power History Integration
The `get_energy_from_power_history` function SHALL propagate the `unit_of_measurement` from the first HA history state entry to all subsequent entries that lack attributes, and SHALL apply the resolved unit when converting each state's power value to kilowatts.

#### Scenario: Attributes only on first entry
- **WHEN** the HA history API includes attributes only on the first entry of a series
- **THEN** the function does not rely on every state entry having its own `unit_of_measurement`

#### Scenario: Unit conversion to kW
- **WHEN** a power value is converted to kW
- **THEN** `"W"` is divided by 1000 and `"MW"` is multiplied by 1000
- **AND** `"kW"` (or any other or absent unit) is used as-is

#### Scenario: HA history returns the unit only on the first entry

- **WHEN** the first state entry has `attributes: {"unit_of_measurement": "W"}` with value `3164` and the subsequent entries have `attributes: {}` with values `3124`, `3147`, and `0`
- **THEN** the function SHALL apply the `"W"` unit to ALL entries
- **AND** every value SHALL be divided by 1000 before integration (3.164 kW, 3.124 kW, 3.147 kW, 0 kW)
- **AND** the integrated slot energy SHALL be on the order of ~0.78 kWh, not ~780 kWh

#### Scenario: Subsequent entry reports watts without a unit

- **WHEN** the first state carries `unit_of_measurement: "W"` and a later state has no `unit_of_measurement`
- **THEN** the later state's value SHALL be treated as watts and divided by 1000
- **AND** the value SHALL NOT be treated as kilowatts

#### Scenario: No state entry has a unit attribute

- **WHEN** no state entry in the series carries a `unit_of_measurement`
- **THEN** the function SHALL treat all power values as already being in kW
- **AND** SHALL integrate them without dividing or multiplying

#### Scenario: Unit changes mid-series

- **WHEN** a later state entry introduces a different `unit_of_measurement` (e.g. sensor reconfigured from `"W"` to `"kW"`)
- **THEN** the function SHALL adopt the new unit from that entry onward
- **AND** SHALL keep applying the previous unit to the entries before the change

#### Scenario: Water-heater and EV-charger energy use the same path

- **WHEN** the recorder computes `water_kwh` for a water heater or `ev_charging_kwh` for an EV charger from a power sensor via `get_energy_from_power_history`
- **THEN** both SHALL benefit from the same first-state unit propagation
- **AND** a heater drawing ~3 kW for a full 15-minute slot SHALL record ~0.75 kWh rather than a spike that the validation guard zeroes

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
The recorder SHALL store per-device water energy in versioned existing slot observation metadata, keyed by heater ID, without a database schema change. Reads SHALL return attributable energy, measurement source, coverage and active-energy semantics. Accepted corrections SHALL update water energy and its device metadata together; unrelated and retained authoritative metadata SHALL be preserved.

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
- **AND** known measured idle heaters SHALL have explicit zero-valued entries; when no heaters are enabled the mapping SHALL be `{}` or omitted

#### Scenario: Stored mapping survives restart and correction
- **WHEN** the recorder writes heater A at 0.75 kWh and heater B at 0.50 kWh through the observation store and the process restarts
- **THEN** reading the slot SHALL return both device values and their source/semantics metadata
- **AND** a subsequent accepted correction to A SHALL update its value and attribution together without losing unrelated metadata

#### Scenario: Legacy aggregate cannot establish ownership
- **WHEN** a legacy observation contains only aggregate water energy and sole-heater ownership for that window cannot be established
- **THEN** the reader SHALL NOT assign or split that energy among current heater IDs
- **AND** it SHALL attempt reconstruction from available power history and otherwise report unavailable device attribution

#### Scenario: Legacy energy semantics are not invented
- **WHEN** historical water energy lacks evidence that an idle cutoff was applied
- **THEN** it SHALL retain legacy semantics and SHALL NOT be relabelled as filtered active energy
- **AND** a current device count of one alone SHALL NOT certify historical sole ownership

### Requirement: Consistent per-heater active-power normalization
The system SHALL apply each heater's finite non-negative `idle_power_threshold_kw` after power-unit conversion and before integrating energy. Samples below the cutoff SHALL contribute zero active-heating power; samples at or above the cutoff SHALL retain their normalized power. The default SHALL be 0 for backward compatibility.

#### Scenario: Same rule on all paths
- **WHEN** history integration, snapshot fallback, backfill, recent planner progress, live load disaggregation or heating activity detection evaluates heater power
- **THEN** each uses the same idle-threshold rule

#### Scenario: Filtered energy and base load
- **WHEN** water energy is filtered by the idle threshold
- **THEN** the filtered water energy is subtracted from total load
- **AND** excluded idle consumption remains in household base load
- **AND** metered grid energy is unchanged

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

#### Scenario: Fallback and backfill match live recording
- **WHEN** live history, snapshot fallback, backfill or recent progress handles the same normalized samples and configured cutoff
- **THEN** they SHALL classify idle and active power consistently and retain truthful measurement provenance

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
The recorder SHALL fall back to power-snapshot based estimation (kW × 0.25 h) for a metric when power-history integration returns no value for that metric. The snapshot SHALL use the same sign rules and inversion flags as the integration. There SHALL be no other fallback.

#### Scenario: History unavailable for PV
- **WHEN** power-history integration returns no value for `pv_power`
- **THEN** the recorder SHALL store `pv_power_kw × 0.25` as `pv_kwh`

#### Scenario: History API unavailable for EV
- **WHEN** power-history integration returns no value for an EV charger power sensor
- **THEN** the recorder SHALL use `ev_power_kw × 0.25` for that charger

#### Scenario: History API unavailable for water heater
- **WHEN** power-history integration returns no value for a water heater power sensor
- **THEN** the recorder SHALL use `water_power_kw × 0.25` for that heater

#### Scenario: Battery snapshot is sign-gated
- **WHEN** power-history integration returns no value for `battery_power` and the inversion-adjusted snapshot is `−1.2 kW`
- **THEN** the recorder SHALL store `batt_charge_kwh = 0.3` and `batt_discharge_kwh = 0`

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
The backfill path SHALL filter spikes with the config-derived `max_kwh_per_slot` (`get_max_energy_per_slot`) via the same validation as the live recorder, instead of a hardcoded value.

#### Scenario: Backfill filters spikes using config threshold
- **WHEN** backfill integrates a slot value that exceeds `max_kwh_per_slot`
- **THEN** that value SHALL be set to `0.0` before storage

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

### Requirement: Load Isolation from Deferrable Loads
Every writer of `slot_observations` — the live recorder AND the backfill path — SHALL subtract energy from controllable loads (EV charging, water heating) from the total load before storing `load_kwh`, so that `load_kwh` always represents base load only. The controllable-load energy used for the subtraction SHALL be the integrated energy for that same completed slot, falling back to the power snapshot only when history is unavailable.

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
- **THEN** the writer SHALL clamp `load_kwh` to `0.0` and log a warning

#### Scenario: Load snapshot fallback uses disaggregated base load
- **WHEN** power-history integration returns no value for `load_power`
- **AND** the LoadDisaggregator provides `base_load_kw` from power snapshot isolation
- **THEN** the recorder SHALL use `base_load_kw × 0.25` for `load_kwh` without subtracting EV and water a second time

#### Scenario: Backfill disaggregates exactly like the live path
- **WHEN** backfill integrates total load of `5.0 kWh` for a missing slot
- **AND** EV charging consumed `2.0 kWh` and water heating `0.5 kWh` during that slot
- **THEN** backfill SHALL store `2.5 kWh` as `load_kwh`

### Requirement: Slot Alignment to Completed Window
The recorder SHALL record the 15-minute slot that has just **finished**, labeling the row with `slot_start = floor(now) − 15 minutes` and computing every energy field over the single window `[slot_start, slot_start + 15 min]`. The `slot_start` label SHALL be derived from the wall-clock time, not from a loop iteration counter, so a late or skipped wake still labels the correct completed slot.

#### Scenario: Steady-state wake records the finished slot
- **WHEN** the recorder wakes at `12:15:04` (just after the boundary)
- **THEN** it SHALL record the slot labeled `slot_start = 12:00`
- **AND** all energy fields SHALL describe the window `[12:00, 12:15]`

#### Scenario: All fields align to one window
- **WHEN** the recorder records the `12:00` slot
- **THEN** PV, load, grid, battery, EV and water energy SHALL all be integrated over `[12:00, 12:15]` — no field is shifted to a different slot

#### Scenario: Late wake still labels correctly
- **WHEN** the recorder wakes at `12:33` after missing the `12:15` boundary
- **THEN** it SHALL derive `slot_start` from the wall clock (the completed `12:15` slot) rather than assuming the previous iteration's slot

### Requirement: Correctable Energy Storage
The slot-observation UPSERT SHALL distinguish "no measurement available" (skip the column, keep any existing value) from "a real measurement" (write it). Non-authoritative backfill writes SHALL only fill columns that have no authoritative measurement yet and SHALL NOT overwrite an authoritative value.

#### Scenario: Authoritative corrections and zeros
- **WHEN** the authoritative live recorder writes a real measurement lower than, or equal to zero relative to, the stored value
- **THEN** it is written, so over-counts can be corrected and genuine zeros can be stored

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

### Requirement: Single Live Recorder Instance
Exactly one live recorder instance SHALL write `slot_observations` energy and price columns at runtime, and the in-process `RecorderService` (started by `backend/main.py`) SHALL be that single canonical recorder. Container entrypoints SHALL NOT additionally launch the standalone `python -m backend.recorder` loop alongside the application server.

#### Scenario: No concurrent recorders
- **WHEN** the deployment runtime starts
- **THEN** it does not start more than one concurrent recorder

#### Scenario: Last-writer-wins rationale
- **WHEN** authoritative writes occur
- **THEN** they use last-writer-wins so genuine zeros and downward corrections can be stored
- **AND** a single live recorder keeps those writes well-defined and avoids duplicate history requests for the same slot

#### Scenario: Application server starts exactly one recorder
- **WHEN** the container starts the application server (`uvicorn backend.main:app`)
- **THEN** the in-process `RecorderService` SHALL be the only recorder loop running
- **AND** no standalone `python -m backend.recorder` process SHALL be launched alongside it

#### Scenario: Entrypoint does not launch a standalone recorder
- **WHEN** `scripts/docker-entrypoint.sh` runs
- **THEN** it SHALL NOT invoke `python -m backend.recorder` (neither at initial startup nor in any process-monitor/restart block)
- **AND** it SHALL rely on the application server's in-process recorder for live observation recording

#### Scenario: Add-on and root entrypoints are consistent
- **WHEN** the system is deployed via either the root `Dockerfile` (`scripts/docker-entrypoint.sh`) or the HA add-on Dockerfiles (`darkstar/run.sh`, `darkstar-dev/run.sh`)
- **THEN** both topologies SHALL run exactly one live recorder (the in-process `RecorderService`)

### Requirement: Canonical Column Ownership
Each `slot_observations` column SHALL have exactly one canonical owner. The recorder SHALL be the sole writer of the energy and price columns (including `load_kwh` as base load, `pv_kwh`, grid columns, `ev_charging_kwh`/`water_kwh` and their per-device JSON, and price columns). The executor SHALL be the sole writer of `executed_action`. No column SHALL be written by both owners.

#### Scenario: Recorder owns energy columns
- **WHEN** the executor records what it did for a slot
- **THEN** it SHALL write only `executed_action` (keyed on `slot_start`) and SHALL NOT write any energy or price column

#### Scenario: Executor write does not clobber recorder columns
- **WHEN** the executor updates `executed_action` for a slot the recorder also wrote
- **THEN** the recorder-owned energy/price columns for that slot SHALL be unaffected

### Requirement: All slot energy is integrated from power history
The recorder SHALL compute `pv_kwh`, total load, `import_kwh`, `export_kwh`, `batt_charge_kwh`, `batt_discharge_kwh`, `ev_charging_kwh` and `water_kwh` for the completed slot by step-integrating (zero-order hold) the configured power sensors' HA history over exactly `[slot_start, slot_end]`. This SHALL be the only primary method; the system SHALL NOT read cumulative energy counters for any metric.

#### Scenario: Power sensors used
- **WHEN** the recorder integrates a completed slot
- **THEN** it uses `input_sensors.pv_power`, `load_power`, `grid_power` (net meter) or `grid_import_power` and `grid_export_power` (dual meter), and `battery_power`
- **AND** it uses each enabled EV charger's `sensor` and each enabled water heater's `sensor`

#### Scenario: Disabled subsystem
- **WHEN** `has_solar`, `has_battery`, `has_ev_charger` or `has_water_heater` is false
- **THEN** the subsystem's metrics are recorded as `0.0` without fetching history

#### Scenario: Load starting mid-slot is placed in the right slot
- **WHEN** the grid power is `0.3 kW` until `00:15:08` and `7.2 kW` from `00:15:09` to the end of the slot `[00:15, 00:30]`
- **THEN** the recorder SHALL store `import_kwh` equal to the integral over `[00:15, 00:30]` (about 1.8 kWh)

#### Scenario: EV charge-start slot has import at least equal to the EV share
- **WHEN** an EV charges at about 6.9 kW from `00:15:10` to the end of the `[00:15, 00:30]` slot with house load of about 0.25 kWh in the slot and no PV or battery discharge
- **THEN** the stored `import_kwh` SHALL be at least the stored `ev_charging_kwh` within sensor tolerance
- **AND** `load_kwh` SHALL NOT be clamped to 0

#### Scenario: Battery energy comes from battery power history
- **WHEN** the battery power is `−2.0 kW` (charging) for the first 6 minutes of a slot and `+1.0 kW` (discharging) for the remaining 9 minutes
- **THEN** the recorder SHALL store `batt_charge_kwh = 0.2` and `batt_discharge_kwh = 0.15`

#### Scenario: Disabled subsystem records zero without a request
- **WHEN** `system.has_battery` is false
- **THEN** `batt_charge_kwh` and `batt_discharge_kwh` SHALL be `0.0`
- **AND** no history SHALL be requested for `battery_power`

### Requirement: Signed power is split by sign per sample interval
The integrator SHALL return the positive and negative energy of a power series separately, accumulating each sample interval into one side by the sign of its held value. Inversion flags SHALL be applied before splitting.

#### Scenario: Net grid split
- **WHEN** a net grid series is split after `input_sensors.grid_power_inverted` is applied
- **THEN** the positive part is `import_kwh` and the magnitude of the negative part is `export_kwh`

#### Scenario: Battery split
- **WHEN** a battery series is split after `input_sensors.battery_power_inverted` is applied
- **THEN** the positive part is `batt_discharge_kwh` and the magnitude of the negative part is `batt_charge_kwh`

#### Scenario: Unsigned series
- **WHEN** PV, load, dual-meter import and export, EV or water series have negative samples
- **THEN** the negative samples contribute `0`

#### Scenario: Net meter splits import and export
- **WHEN** a net grid power sensor is `+2.0 kW` for the first 5 minutes of a slot and `−4.0 kW` for the remaining 10 minutes
- **THEN** the recorder SHALL store `import_kwh = 0.1667` and `export_kwh = 0.6667`

#### Scenario: Inverted net meter
- **WHEN** `grid_power_inverted` is true and the raw sensor reads `−3.0 kW` for the whole slot
- **THEN** the recorder SHALL store `import_kwh = 0.75` and `export_kwh = 0`

#### Scenario: Inverted battery sensor
- **WHEN** `battery_power_inverted` is true and the raw sensor reads `+2.0 kW` for the whole slot
- **THEN** the recorder SHALL store `batt_charge_kwh = 0.5` and `batt_discharge_kwh = 0`

#### Scenario: Dual meter integrates both sensors
- **WHEN** the grid meter type is dual and the import and export power sensors hold `1.0 kW` and `0 kW` over the slot
- **THEN** the recorder SHALL store `import_kwh = 0.25` and `export_kwh = 0`

#### Scenario: EV and water results are unchanged
- **WHEN** the recorder integrates an EV charger or water heater power sensor
- **THEN** the result SHALL equal the value the previous `get_energy_from_power_history` produced for the same history

### Requirement: One batched history request per slot
The recorder SHALL fetch the history of all power entities needed for a slot in a single HA History API request (comma-separated `filter_entity_id`, same timeout as the existing power-history function) and integrate each entity from that response. If the request fails, every metric SHALL use its snapshot fallback for that slot and the failure SHALL be logged once at warning level. An entity missing from an otherwise successful response SHALL use its own snapshot fallback.

#### Scenario: Single request for all entities
- **WHEN** the recorder records a slot with PV, load, net grid, battery, one EV charger and one water heater configured
- **THEN** exactly one HA history request SHALL be made for that slot

#### Scenario: Request failure falls back per metric
- **WHEN** the batched history request times out
- **THEN** every metric SHALL be recorded from its power snapshot × 0.25 h
- **AND** one warning SHALL be logged

#### Scenario: One entity has no history
- **WHEN** the response contains no valid samples for `pv_power` but valid samples for the other entities
- **THEN** only `pv_kwh` SHALL use the snapshot fallback

### Requirement: Backfill integrates power history
The backfill path SHALL fill missing slots (from the last observation to now, capped at 10 days) by integrating the same power entities as the live recorder over each 15-minute slot, using the same integrator, sign rules and load isolation, and SHALL write with `authoritative=False`. History SHALL be fetched in batched requests that each cover at most one local day. The backfill path SHALL NOT read cumulative energy counters. Battery charge and discharge SHALL be backfilled.

#### Scenario: Gap is filled from power history
- **WHEN** the last observation is `08:00` and the service starts at `11:07`
- **THEN** backfill SHALL write slots `08:15` through `10:45` with PV, load, grid, battery, EV and water energy integrated from power history

#### Scenario: Requests are bounded per day
- **WHEN** backfill covers a 3-day gap
- **THEN** it SHALL make at most 3 history requests, each for all entities over one local day or less

#### Scenario: Gap older than the cap stays unfilled
- **WHEN** the last observation is 14 days ago
- **THEN** backfill SHALL only fill the most recent 10 days

### Requirement: Obsolete recorder state is removed
On startup, the recorder service SHALL delete `data/recorder_state.json` if it exists and log the removal at info level. No component SHALL read or write it afterwards.

#### Scenario: State file left from an earlier version
- **WHEN** the service starts and `data/recorder_state.json` exists
- **THEN** the file SHALL be deleted and an info message logged

#### Scenario: No state file
- **WHEN** the service starts and the file does not exist
- **THEN** startup SHALL proceed without a warning

### Requirement: Actual measurement provenance accompanies recorded values
The recorder SHALL persist versioned per-component measurement provenance and writer ownership, measurement-boundary fingerprint, supported energy-semantics identifier and SoC source/ownership in existing `quality_flags`. Metadata SHALL describe the actual path, not just the application version or successful completion of a history request.

#### Scenario: Source categories distinguished
- **WHEN** provenance is recorded
- **THEN** it distinguishes integrated power history, snapshot estimates, disabled zeros, unconfigured zeros, derived/mixed energy and live/cached SoC
- **AND** derived base load and aggregate device energy reflect all contributing source paths

#### Scenario: Backfill provenance
- **WHEN** a backfill writes values
- **THEN** it retains its non-authoritative source while recording its measurement method
- **AND** this includes accepted components in a partially recorder-owned row

#### Scenario: One missing history entity
- **WHEN** only battery history is missing from a successful batch response
- **THEN** battery energy is labelled as snapshot-derived and other valid integrated fields retain their own history provenance
- **AND** the slot is not falsely labelled wholly integrated

#### Scenario: Zero snapshot contributes to an aggregate
- **WHEN** an enabled EV charger uses a zero-valued snapshot fallback while another charger has integrated energy
- **THEN** aggregate EV and derived base-load provenance reflect the mixed source

#### Scenario: Disabled versus unset
- **WHEN** a subsystem is disabled or an enabled required input is unconfigured
- **THEN** its zero provenance distinguishes those cases rather than treating them as equivalent measurements

#### Scenario: Cached battery charge level
- **WHEN** the recorder uses its last-known SoC fallback
- **THEN** the SoC source is cached and is not labelled live

### Requirement: Measurement metadata follows accepted corrections
Observation UPSERTs SHALL update values and corresponding provenance together. Retained authoritative values SHALL retain their method/ownership metadata, and partial writes SHALL NOT certify untouched fields.

#### Scenario: Corrections and non-authoritative writes
- **WHEN** a correction lacks supported provenance
- **THEN** the overwritten fields are marked unknown
- **AND** non-authoritative writes do not overwrite authoritative battery energy or SoC or relabel retained values

#### Scenario: Flags and attestation
- **WHEN** an ordinary recording write occurs
- **THEN** unrelated flags, especially explicit exclusions, are preserved
- **AND** changed annotated measurements invalidate their legacy attestation

#### Scenario: Partial authoritative correction
- **WHEN** a live write corrects PV but supplies no battery measurement
- **THEN** stored battery energy and its provenance remain unchanged and corrected PV receives its own new provenance

#### Scenario: Backfill collision
- **WHEN** a backfill supplies different battery energy and SoC for a slot already owned by the recorder
- **THEN** retained authoritative values and their provenance are unchanged

#### Scenario: Backfill fills an unmeasured component
- **WHEN** a recorder-owned slot has no authoritative battery measurement and backfill fills it
- **THEN** that accepted battery value is identified as backfill-owned even though the row's overall source remains recorder
- **AND** it is not falsely certified for calibration

#### Scenario: Existing exclusion survives
- **WHEN** a new live observation updates a slot marked `exclude: true`
- **THEN** the exclusion remains set and metadata still truthfully describes accepted measurements

#### Scenario: An attested value changes
- **WHEN** a writer changes an energy or SoC measurement covered by legacy attestation
- **THEN** the stale attestation is invalidated instead of certifying the replacement

### Requirement: Price backfill completes unpriced slots without overwriting priced ones
The price backfill SHALL fill both import and export price of recent slots lacking an import price, from the Nordpool price for that exact slot. It SHALL store the raw Nordpool spot export price (no fees or VAT), write only the slots it patched, and never change prices a slot already has. Priced slots in the window SHALL NOT make the backfill fail, and a repeat run SHALL change nothing.

#### Scenario: Gap slots next to normal slots are priced
- **WHEN** the recent window holds slots with stored prices and gap slots with no prices, and Nordpool has prices for the gap slots
- **THEN** each gap slot SHALL be stored with its import price and its raw spot export price
- **AND** the backfill SHALL complete without error

#### Scenario: Existing prices are preserved
- **WHEN** a slot already has import and export prices and the backfill runs
- **THEN** that slot's prices SHALL be unchanged

#### Scenario: Slot with no Nordpool price stays unpriced
- **WHEN** a gap slot has no matching Nordpool price
- **THEN** that slot SHALL remain unpriced and the other gap slots SHALL still be filled

#### Scenario: Repeated backfill is idempotent
- **WHEN** the backfill runs a second time after filling all gap slots
- **THEN** it SHALL report no missing prices and SHALL NOT write any slot

### Requirement: Recorder derives water recording metadata from active heaters only
The recorder SHALL derive water metadata from `active_water_heaters(config)`, so that `system.has_water_heater: false` yields method `disabled_zero` and `0.0` kWh even when stale heater entries exist.

#### Scenario: Flag off with a stale enabled heater without entities
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters` holds `{id: main_tank, enabled: true, sensor: "", target_entity: ""}`
- **WHEN** the recorder stores a slot
- **THEN** `quality_flags.recording.components.water.method` is `disabled_zero`
- **AND** `water_kwh` is `0.0`
- **AND** the grid-only comparison treats the slot as usable for the water component

#### Scenario: Flag on with an enabled heater without a sensor
- **GIVEN** `system.has_water_heater` is `true` and an enabled heater has an empty `sensor`
- **WHEN** the recorder stores a slot
- **THEN** the water method is `unknown` as before

#### Scenario: Flag off with no heater entries
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters` is empty
- **THEN** the water method is `disabled_zero`

### Requirement: Power History Unit Integrity
When parsing Home Assistant history for a power sensor, the system SHALL learn the unit of measurement from any state that carries it, including `unavailable`/`unknown` states, and apply it to all numeric states of the series that lack one. If no state in the series carries a unit, the system SHALL use the entity's current unit of measurement, for every consumer of power history.

#### Scenario: Series starts with a non-numeric state carrying the unit
- **WHEN** a history chunk for a W sensor starts with an `unavailable` state carrying `unit_of_measurement: W`, followed by unitless numeric states
- **THEN** the numeric states SHALL be interpreted as W and integrated to the correct kWh

#### Scenario: No unit in the series
- **WHEN** no state of a series carries a unit and the entity's current state reports `W`
- **THEN** the series SHALL be interpreted as W

#### Scenario: Unit unknown everywhere
- **WHEN** neither the series nor the current entity state provides a unit
- **THEN** the series SHALL be interpreted as kW and a warning naming the entity SHALL be logged once

#### Scenario: Slot energy after an outage
- **WHEN** the recorder integrates a 15-minute slot whose history starts with an `unavailable` state of a W sensor
- **THEN** the slot energy SHALL be computed in kWh from W, not inflated 1000x

#### Scenario: Normal series unchanged
- **WHEN** the first state of a series is numeric and carries its unit
- **THEN** parsing and integration SHALL give the same result as before

### Requirement: Unknown Power Unit Warning
If neither the history series nor the entity's current state provides a unit, the system SHALL assume kW and log a warning naming the entity, at most once per entity per process.

#### Scenario: Warning not repeated
- **WHEN** the same unitless entity is parsed repeatedly
- **THEN** the warning SHALL be logged only once

### Requirement: Explicit History Request Semantics
The history request SHALL express its intent in terms HA actually honours: all state changes are requested (`significant_changes_only` sent as "0"), and the reduced-payload response form is used deliberately rather than by accident.

#### Scenario: Request parameters
- **WHEN** power history is requested
- **THEN** `significant_changes_only` SHALL be "0" and no boolean `False` SHALL be sent for either flag

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
