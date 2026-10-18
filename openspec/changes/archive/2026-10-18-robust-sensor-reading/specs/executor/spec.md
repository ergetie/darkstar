## ADDED Requirements

## MODIFIED Requirements

### Requirement: Water heater sensor reads are gated by has_water_heater flag
The executor and recorder SHALL NOT fetch water heater power sensors when `system.has_water_heater` is `false`. The `water_heaters[]` sensor loop SHALL be skipped entirely when the system flag is disabled. In addition, the executor SHALL read a water heater's current temperature from its target entity only when `system.has_water_heater` is `true` and that heater's `control_type` is `temperature`; it SHALL NOT attempt a temperature read or parse for any heater with `control_type: switch`. The executor's single `current_water_temp` value is taken from the first configured heater (`water_heater_devices[0]`); when that heater is switch-controlled, no read occurs and `current_water_temp` keeps its default.

#### Scenario: Water heating disabled skips sensor reads
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `false`
- **THEN** no HTTP requests are made for water heater sensors
- **AND** no 404 warnings are logged for missing water heater entities

#### Scenario: Water heating enabled reads sensors normally
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `true`
- **THEN** enabled water heater sensors from `water_heaters[]` are fetched as before

#### Scenario: Switch-controlled heater
- **WHEN** a heater has `control_type: switch` and target entity state "on"
- **THEN** no temperature read or parse is attempted for it, no warning is logged, and `current_water_temp` keeps its default

#### Scenario: Temperature-controlled heater
- **WHEN** the first heater has `control_type: temperature` and the entity state is "55.5"
- **THEN** `current_water_temp` is 55.5

#### Scenario: Mixed multi-device setup
- **WHEN** the first heater is `control_type: temperature` and a second is `control_type: switch`
- **THEN** only the first heater's temperature is read and the second heater's target entity is never parsed as a temperature

## ADDED Requirements

### Requirement: Sensor reads are isolated
A failure to read or parse one sensor SHALL NOT prevent any other sensor from being gathered. Each failure SHALL log a warning naming the entity id and reason, rate-limited per entity so a persistent fault does not log every tick.

#### Scenario: One non-numeric sensor
- **WHEN** one numeric sensor returns a non-numeric state while phase sensors are live
- **THEN** the phase currents are still populated in the system state

#### Scenario: Persistent fault
- **WHEN** the same entity fails on consecutive ticks
- **THEN** a warning with its entity id and reason is logged at most once per rate-limit interval
