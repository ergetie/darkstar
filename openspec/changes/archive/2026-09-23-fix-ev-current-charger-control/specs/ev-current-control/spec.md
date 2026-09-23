## MODIFIED Requirements

### Requirement: Current-type charger actuation
For EV charger devices configured with `type: current`, a `current_entity` and a `switch_entity`, the executor SHALL control charging by writing an integer ampere setpoint to the charger's HA number entity AND by setting the charger's `switch_entity` to its configured `charge_enabled_value` (select-like) or `on` (switch-like). The planner-derived target SHALL be computed as `floor(planned_kw × 1000 / (230 × active_phases))`, clamped to `[min_current_a, max_current_a]`. On start, the setpoint SHALL be written before the switch is enabled. Each write SHALL be idempotent (skipped when the entity already holds the target value). The switch state SHALL be re-checked every tick while charging is desired, and corrected if it differs.

#### Scenario: Planned 11 kW on a 3-phase charger
- **WHEN** the current slot plans 11.0 kW for a 3-phase charger with `max_current_a: 16`
- **THEN** the executor SHALL write a setpoint of 15 A (floor of 11000 / 690)
- **AND** SHALL set the switch entity to the configured `charge_enabled_value`

#### Scenario: Setpoint unchanged between ticks
- **WHEN** the computed setpoint equals the value already set on the charger and the switch already holds the enabled value
- **THEN** no HA service call SHALL be made for that tick

#### Scenario: Charger externally switched off mid-session
- **WHEN** charging is desired and the switch entity reads the disabled value
- **THEN** the executor SHALL set it back to the configured enabled value

### Requirement: Minimum current floor with pause semantics
The executor SHALL never write a setpoint below `min_current_a` (default 6), and SHALL never write 0 A. Whenever charging must stop (the target, planned or balancer-capped, falls below the floor; the plan ends; a load-balancer pause; the safety timeout; manual override or force_stop), the executor SHALL stop charging by setting the `switch_entity` to its configured `charge_disabled_value` (select-like) or `off` (switch-like), and SHALL treat the session as paused rather than failed. No value SHALL be hardcoded.

#### Scenario: Plan implies 4 A
- **WHEN** the planner-derived target computes to 4 A
- **THEN** the executor SHALL set the switch entity to the configured `charge_disabled_value` rather than write 4 A or 0 A

#### Scenario: Plan slot ends
- **WHEN** a current-type charger was charging and the new slot plans 0 kW with no keep-on flag
- **THEN** the executor SHALL set the switch entity to `charge_disabled_value`
- **AND** SHALL NOT call `number.set_value` on the current entity

## ADDED Requirements

### Requirement: Current-type chargers require a switch entity
An enabled charger with `type: current` SHALL have a non-empty `switch_entity`. For a select-like entity, the existing rules SHALL apply: `charge_enabled_value` and `charge_disabled_value` non-empty and different. Config validation SHALL reject a configuration that breaks this rule with an error naming the charger. The settings editor SHALL mark the field as required for current-type chargers and SHALL block saving while it is missing.

#### Scenario: Current charger without switch entity
- **WHEN** config has an enabled `type: current` charger with `switch_entity: ""`
- **THEN** validation SHALL fail with a message naming that charger and the missing `switch_entity`

#### Scenario: Settings editor blocks save
- **WHEN** a user sets a charger to type current and leaves the charging-control entity empty
- **THEN** the editor SHALL show the field as required and SHALL not allow saving
