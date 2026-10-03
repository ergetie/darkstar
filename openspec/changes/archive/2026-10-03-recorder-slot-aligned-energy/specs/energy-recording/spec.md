## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Backfill uses config-derived threshold
The backfill path SHALL filter spikes with the config-derived `max_kwh_per_slot` (`get_max_energy_per_slot`) via the same validation as the live recorder, instead of a hardcoded value.

#### Scenario: Backfill filters spikes using config threshold
- **WHEN** backfill integrates a slot value that exceeds `max_kwh_per_slot`
- **THEN** that value SHALL be set to `0.0` before storage

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

## REMOVED Requirements

### Requirement: Support for Cumulative Energy Sensors
**Reason**: Cumulative counters are replaced by power-history integration for every metric.
**Migration**: The six `input_sensors.total_*` keys are removed by startup config migration; no user action.

### Requirement: Delta-based Energy Calculation
**Reason**: No metric is computed from counter deltas anymore.
**Migration**: Covered by "All slot energy is integrated from power history".

### Requirement: Persistent Recorder State
**Reason**: Integration needs no state across slots.
**Migration**: `data/recorder_state.json` is deleted at startup ("Obsolete recorder state is removed").

### Requirement: Automatic Unit Normalization
**Reason**: Applied only to cumulative energy values. Power unit handling is covered by "Unit Propagation in Power History Integration".
**Migration**: None.

### Requirement: Unit Propagation in History Processing
**Reason**: Described counter history in the load profile, which now uses power history.
**Migration**: Covered by "Unit Propagation in Power History Integration".

### Requirement: Unit Detection Logging
**Reason**: Applied only to cumulative energy normalisation, which is removed.
**Migration**: None.

### Requirement: Battery Cumulative Delta Calculation
**Reason**: Battery energy is integrated from battery power history.
**Migration**: Covered by "All slot energy is integrated from power history" and "Signed power is split by sign per sample interval".

### Requirement: Persistent Sensor Timestamp Storage
**Reason**: Existed only for counter time-scaling in the removed state file.
**Migration**: None.

### Requirement: Backfill Interpolation for Cumulative Sensors
**Reason**: Backfill integrates power history.
**Migration**: Covered by "Backfill integrates power history".
