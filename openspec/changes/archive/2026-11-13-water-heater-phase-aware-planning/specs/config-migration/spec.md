# Spec Delta

## ADDED Requirements

### Requirement: Water heater load phases migrate to the device
`migrate_config()` SHALL, for each `load_balancing.loads[]` entry with `device_type: water_heater` that has a `phases` key, copy those phases to the `water_heaters[]` entry whose `id` equals the load's `device_id` (only when that heater has no `phases` yet), and then remove `phases` from the load entry. Entries of other device types SHALL NOT be changed. The step SHALL be idempotent.

#### Scenario: Phases moved
- **WHEN** `loads` has `{device_type: water_heater, device_id: main_tank, phases: [3]}` and `water_heaters` has `main_tank` without `phases`
- **THEN** `water_heaters[main_tank].phases` is `[3]` and the load entry no longer has `phases`

#### Scenario: Device already has phases
- **WHEN** the heater already has `phases: [1]` and the load has `phases: [3]`
- **THEN** the heater keeps `[1]`, a warning is logged, and the load's `phases` is still removed

#### Scenario: No matching heater
- **WHEN** no heater has the load's `device_id`
- **THEN** the load entry keeps its `phases` and a warning is logged

#### Scenario: Custom load untouched
- **WHEN** a `custom_entity` load has `phases: [2]`
- **THEN** it is unchanged

#### Scenario: Second run
- **WHEN** the migration runs again on a migrated config
- **THEN** nothing changes and no write occurs
