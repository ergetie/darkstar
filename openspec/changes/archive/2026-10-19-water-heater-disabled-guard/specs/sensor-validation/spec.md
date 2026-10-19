## ADDED Requirements

### Requirement: Water heater validation and warnings are skipped when the flag is off
When `system.has_water_heater` is `false`, the health checker, config save validation (including heater control-type and target-entity pairing checks and disabled-heater warnings), planner config check and `validate_water_heating_config` SHALL NOT emit warnings or errors derived from `water_heaters[]` or `water_heating.*`, and stale invalid heater values SHALL NOT block planning or saving.

#### Scenario: Invalid stale heater value with flag off
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters[0].max_hours_between_heating` is `-1`
- **WHEN** config is validated for planning or save
- **THEN** no water validation error is raised

#### Scenario: Same value with flag on
- **GIVEN** `system.has_water_heater` is `true`
- **THEN** the validation error is raised as before

#### Scenario: No water health issues with flag off
- **GIVEN** the flag is `false` and an enabled heater lacks a `sensor` or `power_kw`
- **WHEN** health is checked
- **THEN** no water-related issue is reported

#### Scenario: Heater pairing mismatch with flag off
- **GIVEN** the flag is `false` and a heater has `control_type: temperature` with a `switch.` target entity
- **WHEN** config is validated for save
- **THEN** no pairing error or warning is raised
