# synthetic-load-baseline Specification

## Purpose
Provide a dedicated synthetic daily load baseline and migrate legacy numeric consumption values.

## Requirements

### Requirement: Dedicated synthetic load key
The config SHALL provide `input_sensors.synthetic_daily_load_kwh` (default `null`). When `total_load_consumption` is not a configured sensor and `synthetic_daily_load_kwh` is a positive number, the load forecast fallback SHALL generate the synthetic profile scaled to that value.

#### Scenario: Synthetic estimate used
- **WHEN** `total_load_consumption` is empty and `synthetic_daily_load_kwh` is `20`
- **THEN** the fallback load profile SHALL total 20 kWh per day and status SHALL be `synthetic`

#### Scenario: Sensor takes precedence
- **WHEN** both a sensor and `synthetic_daily_load_kwh` are configured
- **THEN** the sensor data SHALL be used

### Requirement: Migration of numeric load value
Startup migration SHALL move a numeric `input_sensors.total_load_consumption` value into `synthetic_daily_load_kwh` and set `total_load_consumption` to empty. The migration SHALL be idempotent.

#### Scenario: Legacy numeric value
- **WHEN** config contains `total_load_consumption: "18"`
- **THEN** after migration `synthetic_daily_load_kwh` SHALL be `18` and `total_load_consumption` SHALL be `""`

#### Scenario: Sensor value untouched
- **WHEN** `total_load_consumption` is `sensor.house_energy`
- **THEN** migration SHALL not change it
