## MODIFIED Requirements

### Requirement: Dedicated synthetic load key
The config SHALL provide `input_sensors.synthetic_daily_load_kwh` (default `null`). When the load profile cannot be built from `input_sensors.load_power` history (sensor not configured, no valid history, or data discarded as implausible) and `synthetic_daily_load_kwh` is a positive number, the load forecast fallback SHALL generate the synthetic profile scaled to that value.

#### Scenario: Synthetic estimate used when history is unusable
- **WHEN** `load_power` history has no valid samples and `synthetic_daily_load_kwh` is `20`
- **THEN** the fallback load profile SHALL total 20 kWh per day and status SHALL be `synthetic`

#### Scenario: Load power history takes precedence
- **WHEN** `load_power` history yields a valid profile and `synthetic_daily_load_kwh` is set
- **THEN** the history-based profile SHALL be used

#### Scenario: No synthetic value and no usable history
- **WHEN** `load_power` history is unusable and `synthetic_daily_load_kwh` is `null`
- **THEN** the demo profile SHALL be used with a degraded status

### Requirement: Migration of numeric load value
Startup migration SHALL move a numeric `input_sensors.total_load_consumption` value into `synthetic_daily_load_kwh` when that is unset, before the counter keys are removed. The migration SHALL be idempotent.

#### Scenario: Legacy numeric value
- **WHEN** config contains `total_load_consumption: "18"`
- **THEN** after migration `synthetic_daily_load_kwh` SHALL be `18` and `total_load_consumption` SHALL be absent

#### Scenario: Sensor value removed without copying
- **WHEN** `total_load_consumption` is `sensor.house_energy`
- **THEN** migration SHALL not change `synthetic_daily_load_kwh` and SHALL remove `total_load_consumption`
