## Purpose

TBD - Energy recording capability for accurate historical energy tracking using step-integrated power sensor history.
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

### Requirement: Unit Propagation in Power History Integration

The `get_energy_from_power_history` function SHALL propagate the `unit_of_measurement` from the first HA history state entry to all subsequent entries that lack attributes, and SHALL apply the resolved unit when converting each state's power value to kilowatts. The HA history API only includes attributes on the first entry in a response series — the function MUST NOT rely on every state entry having its own `unit_of_measurement`. Power values SHALL be converted to kW as: `"W"` divided by 1000, `"MW"` multiplied by 1000, and `"kW"` (or any other / absent unit) used as-is.

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

### Requirement: Single Live Recorder Instance
Exactly one live recorder instance SHALL write `slot_observations` energy and price columns at runtime. The deployment runtime SHALL NOT start more than one concurrent recorder, and the in-process `RecorderService` (started by `backend/main.py`) SHALL be the single canonical live recorder. Container entrypoints SHALL NOT additionally launch the standalone `python -m backend.recorder` loop alongside the application server.

Authoritative writes use last-writer-wins (so genuine zeros and downward corrections can be stored); a single live recorder keeps those writes well-defined and avoids duplicate history requests for the same slot.

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

The power sensors used SHALL be `input_sensors.pv_power`, `load_power`, `grid_power` (net meter) or `grid_import_power` and `grid_export_power` (dual meter), `battery_power`, each enabled EV charger's `sensor` and each enabled water heater's `sensor`. Metrics for a subsystem that is disabled (`has_solar`, `has_battery`, `has_ev_charger`, `has_water_heater` false) SHALL be recorded as `0.0` without fetching history.

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

- Net grid: after `input_sensors.grid_power_inverted`, the positive part SHALL be `import_kwh` and the magnitude of the negative part SHALL be `export_kwh`.
- Battery: after `input_sensors.battery_power_inverted`, the positive part SHALL be `batt_discharge_kwh` and the magnitude of the negative part SHALL be `batt_charge_kwh`.
- PV, load, dual-meter import and export, EV and water: negative samples SHALL contribute `0`.

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
The recorder SHALL persist versioned per-component measurement provenance and writer ownership, measurement-boundary fingerprint, supported energy-semantics identifier and SoC source/ownership in existing `quality_flags`. It SHALL distinguish integrated power history, snapshot estimates, disabled zeros, unconfigured zeros, derived/mixed energy and live/cached SoC. Derived base load and aggregate device energy SHALL reflect all contributing source paths. Metadata SHALL describe the actual path, not just the application version or successful completion of a history request. Backfills SHALL retain their non-authoritative source while recording their measurement method, including accepted components in a partially recorder-owned row.

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
Observation UPSERTs SHALL update values and corresponding provenance together. Retained authoritative values SHALL retain their method/ownership metadata; partial writes SHALL NOT certify untouched fields. Corrections without supported provenance SHALL mark overwritten fields unknown. Non-authoritative writes SHALL NOT overwrite authoritative battery energy or SoC or relabel retained values. Ordinary recording writes SHALL preserve unrelated flags, especially explicit exclusions. Changed annotated measurements SHALL invalidate their legacy attestation.

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
