## ADDED Requirements

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
