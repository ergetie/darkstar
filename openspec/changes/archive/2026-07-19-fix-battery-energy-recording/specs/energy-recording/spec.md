## MODIFIED Requirements

### Requirement: Support for Cumulative Energy Sensors
The system SHALL support configuring cumulative energy sensors (meter readings) in `input_sensors` for PV, Load, Grid, and Battery. These sensors represent total energy processed over the device's lifetime.

#### Scenario: User configures a total PV production sensor
- **WHEN** the user adds `total_pv_production: sensor.pv_energy_total` to `input_sensors` in `config.yaml`
- **THEN** the system SHALL recognize this as a cumulative source for PV energy calculation

#### Scenario: User configures battery charge/discharge sensors
- **WHEN** the user adds `total_battery_charge: sensor.inverter_total_battery_charge` and `total_battery_discharge: sensor.inverter_total_battery_discharge` to `input_sensors` in `config.yaml`
- **THEN** the system SHALL recognize these as cumulative sources for `batt_charge_kwh` and `batt_discharge_kwh` calculation, respectively

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

#### Scenario: Battery falls back to snapshot when no cumulative sensor is configured
- **WHEN** neither `total_battery_charge` nor `total_battery_discharge` is configured in `input_sensors`
- **THEN** the recorder SHALL use the instantaneous `battery_power` snapshot (`battery_kw * 0.25`, sign-gated for charge vs. discharge) exactly as it does today

#### Scenario: Battery charge side falls back independently of discharge side
- **WHEN** `total_battery_charge` is configured but `total_battery_discharge` is not (or vice versa)
- **THEN** the configured side SHALL use its cumulative sensor delta
- **AND** the unconfigured side SHALL use the power-snapshot method for that slot

## ADDED Requirements

### Requirement: Battery Cumulative Delta Calculation
The recorder SHALL calculate `batt_charge_kwh` and `batt_discharge_kwh` from the configured `total_battery_charge` and `total_battery_discharge` cumulative sensors independently, using the same delta-based calculation (including time-proportional scaling and meter-reset detection) already used for PV, load, and grid energy. Each side SHALL fall back to the power-snapshot method only for the slots where its own cumulative sensor is unavailable or its meter reset — the charge and discharge sides SHALL NOT share a single fallback decision.

#### Scenario: Recorder calculates battery charge energy from cumulative delta
- **WHEN** the recorder has a previous reading of `500.0 kWh` for `total_battery_charge` at `12:00`
- **AND** the current reading at `12:15` is `501.2 kWh`
- **THEN** the recorder SHALL store `1.2 kWh` as `batt_charge_kwh` for the `12:00` slot

#### Scenario: Recorder calculates battery discharge energy from cumulative delta
- **WHEN** the recorder has a previous reading of `300.0 kWh` for `total_battery_discharge` at `12:00`
- **AND** the current reading at `12:15` is `301.5 kWh`
- **THEN** the recorder SHALL store `1.5 kWh` as `batt_discharge_kwh` for the `12:00` slot

#### Scenario: Battery meter reset falls back for that side only
- **WHEN** the `total_battery_discharge` cumulative reading decreases between two consecutive slots (meter reset)
- **THEN** the recorder SHALL use the power-snapshot method for `batt_discharge_kwh` in that slot
- **AND** `batt_charge_kwh` SHALL continue to use its own cumulative delta if `total_battery_charge` is unaffected

#### Scenario: Battery power inversion flag does not apply to cumulative sensors
- **WHEN** `input_sensors.battery_power_inverted` is `true`
- **AND** the recorder calculates `batt_charge_kwh`/`batt_discharge_kwh` from the cumulative sensors
- **THEN** the inversion flag SHALL NOT be applied to the cumulative deltas (it continues to apply only to the instantaneous `battery_power` snapshot fallback)

#### Scenario: Cold start after deploy falls back for one slot
- **WHEN** the recorder has no prior state for `battery_charge_total` or `battery_discharge_total` (first run after this change is deployed)
- **THEN** the recorder SHALL use the power-snapshot method for that side for that one slot
- **AND** subsequent slots SHALL use the cumulative delta once a prior reading exists
