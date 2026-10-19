## ADDED Requirements

### Requirement: Planner derives water heaters from the has_water_heater flag in one place
The planner SHALL obtain the list of heaters to plan only from `active_water_heaters(config)`, which returns an empty list when `system.has_water_heater` is `false` and otherwise the enabled heaters. When it is empty, no code path SHALL create `WaterHeaterInput` entries, force-ON slots, water progress reads, water quota or anti-legionella heating, regardless of `water_heaters[]` content or vacation mode.

#### Scenario: Vacation mode with flag off and anti-legionella due
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters[]` has an enabled heater
- **AND** vacation mode is enabled and the anti-legionella interval has elapsed with local hour >= 14
- **WHEN** the planner runs
- **THEN** `kepler_config.water_heaters` is empty, no water kWh is planned, and `schedule_anti_legionella` is false
- **AND** the anti-legionella record is neither read nor written

#### Scenario: Vacation mode with flag on and anti-legionella due
- **GIVEN** `system.has_water_heater` is `true` and vacation mode is enabled
- **WHEN** the anti-legionella cycle is due
- **THEN** the enabled heaters are planned with `min_kwh_per_day = power_kw * duration_hours`

#### Scenario: Adapter ignores configured heaters when flag off
- **WHEN** `config_to_kepler_config` is called with `has_water_heater=false` and configured heaters
- **THEN** the result has no water heaters

#### Scenario: Mid-block detection ignores heaters when flag off
- **WHEN** the planner runs with the flag off and a previous schedule that heated a configured heater
- **THEN** no forced-ON water slots are produced

### Requirement: Schedule API omits water heating when the flag is off
When `system.has_water_heater` is `false`, `/api/schedule` SHALL return `water_heating_kw` and `planned_water_heating_kw` as 0 and SHALL omit `planned_water_heaters` and `actual_water_heaters_kw` for every planned or not-yet-completed slot. Completed (historical) slots SHALL keep their recorded and planned water fields unchanged.

#### Scenario: Planned water hidden, history kept
- **GIVEN** the flag is `false`, a completed slot has water energy and a current or future slot has planned water
- **WHEN** the schedule is fetched
- **THEN** the completed slot's water fields are unchanged and the planned slot's water fields are 0 with no per-heater lists
