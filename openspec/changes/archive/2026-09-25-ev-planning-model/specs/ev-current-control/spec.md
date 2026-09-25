## MODIFIED Requirements

### Requirement: Current-type charger actuation
For EV charger devices configured with `type: current`, a `current_entity` and a `switch_entity`, the executor SHALL control charging with two writes:
- an integer ampere setpoint to the charger's HA number entity;
- the charger's `switch_entity` set to its configured `charge_enabled_value` (select-like) or `on` (switch-like).

The planner-derived target SHALL be computed as `ceil(planned_kw × 1000 / (V × active_phases))`, with a small epsilon so exact multiples do not round up. `V` is the same nominal voltage used by the shared charger-power helper (`system.grid.nominal_voltage_v`, default 230). The target SHALL be clamped to `[min_current_a, max_current_a]`, so the commanded power is never below the planned power.

On start, the setpoint SHALL be written before the switch is enabled. Each write SHALL be idempotent (skipped when the entity already holds the target value). The switch state SHALL be re-checked every tick while charging is desired, and corrected if it differs.

#### Scenario: Planned maximum on a 3-phase charger
- **WHEN** the current slot plans 11.0 kW for a 3-phase charger with `max_current_a: 16` at 230 V
- **THEN** the executor SHALL write a setpoint of 16 A (ceil of 11000 / 690)
- **AND** SHALL set the switch entity to the configured `charge_enabled_value`

#### Scenario: Planned 4.8 kW on a 3-phase charger
- **WHEN** the current slot plans 4.8 kW for a 3-phase charger at 230 V
- **THEN** the executor SHALL write a setpoint of 7 A (not 6 A)

#### Scenario: Exact multiple does not round up
- **WHEN** the plan is exactly 4.14 kW on 3 phases at 230 V (6 A × 690 W)
- **THEN** the setpoint SHALL be 6 A

#### Scenario: Configured voltage is honoured
- **WHEN** nominal voltage is 240 and the plan is 7.2 kW on 3 phases
- **THEN** the setpoint SHALL be 10 A

#### Scenario: Setpoint unchanged between ticks
- **WHEN** the computed setpoint equals the value already set on the charger and the switch already holds the enabled value
- **THEN** no HA service call SHALL be made for that tick

#### Scenario: Charger externally switched off mid-session
- **WHEN** charging is desired and the switch entity reads the disabled value
- **THEN** the executor SHALL set it back to the configured enabled value
