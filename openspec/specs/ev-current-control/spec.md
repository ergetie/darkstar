# Spec: EV Current Control

## Purpose

Defines how the executor controls current-type EV chargers (ampere setpoint via an HA number entity) as an alternative to binary switch control, including kW→A translation, minimum-current pause semantics, active phase detection, and migration of the legacy singular EV charger config stub.

## Requirements

### Requirement: Current-type charger actuation
For EV charger devices configured with `type: current`, a `current_entity` and a `switch_entity`, the executor SHALL control charging by writing an integer ampere setpoint to the charger's HA number entity AND by setting the charger's `switch_entity` to its configured `charge_enabled_value` (select-like) or `on` (switch-like). The planner-derived target SHALL be computed as `ceil(planned_kw × 1000 / (230 × active_phases))` (with a small epsilon so exact multiples do not round up), clamped to `[min_current_a, max_current_a]`, so the commanded power is never below the planned power. On start, the setpoint SHALL be written before the switch is enabled. Each write SHALL be idempotent (skipped when the entity already holds the target value). The switch state SHALL be re-checked every tick while charging is desired, and corrected if it differs.

#### Scenario: Planned 11 kW on a 3-phase charger
- **WHEN** the current slot plans 11.0 kW for a 3-phase charger with `max_current_a: 16`
- **THEN** the executor SHALL write a setpoint of 16 A (ceil of 11000 / 690)
- **AND** SHALL set the switch entity to the configured `charge_enabled_value`

#### Scenario: Planned 4.8 kW on a 3-phase charger
- **WHEN** the current slot plans 4.8 kW for a 3-phase charger
- **THEN** the executor SHALL write a setpoint of 7 A (not 6 A)

#### Scenario: Exact multiple does not round up
- **WHEN** the plan is exactly 4.14 kW on 3 phases (6 A × 690 W)
- **THEN** the setpoint SHALL be 6 A

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

### Requirement: Active phase count from charger measurement
The executor SHALL determine how many phases the car actually draws on from the charger's per-phase power/current sensors when available, and use that count for kW→A translation and for balancer phase accounting. Before the first measurement of a session, the configured `phases` declaration SHALL be used.

#### Scenario: Car charges on one phase despite 3-phase wiring
- **WHEN** charger sensors show current on L1 only during an active session
- **THEN** kW→A translation SHALL use 1 phase (planned 3.6 kW → 15 A)
- **AND** the balancer SHALL treat the charger as loading L1 only

### Requirement: Binary chargers remain unchanged
Devices with `type: binary` (or absent type) SHALL keep the existing ON/OFF switch behavior, including the 30-minute safety timeout, per-device state tracking, and source isolation. Current-type devices SHALL retain the same safety timeout and source isolation semantics.

#### Scenario: Mixed fleet
- **WHEN** one charger is `type: binary` and another is `type: current`
- **THEN** the binary charger is switch-controlled and the current charger is setpoint-controlled, independently

#### Scenario: Source isolation with current control
- **WHEN** a current-type charger is actively charging at any setpoint
- **THEN** battery discharge SHALL be blocked exactly as for binary chargers

### Requirement: Legacy singular EV charger stub is removed
The unused `executor.ev_charger` config block (`control_entity`, `control_mode`, `max_current_a`, `enabled_entity`) SHALL be removed. Config migration SHALL map its fields onto the first `ev_chargers[]` device when present (control_entity → current_entity, max_current_a → max_current_a, control_mode "current" → type current) and log the migration.

#### Scenario: User with the legacy stub upgrades
- **WHEN** config contains `executor.ev_charger.control_mode: "current"` with a control entity
- **THEN** migration SHALL move those values onto `ev_chargers[0]` and remove the stub block

### Requirement: Current-type chargers require a switch entity
An enabled charger with `type: current` SHALL have a non-empty `switch_entity`. For a select-like entity, the existing rules SHALL apply: `charge_enabled_value` and `charge_disabled_value` non-empty and different. Config validation SHALL reject a configuration that breaks this rule with an error naming the charger. The settings editor SHALL mark the field as required for current-type chargers and SHALL block saving while it is missing.

#### Scenario: Current charger without switch entity
- **WHEN** config has an enabled `type: current` charger with `switch_entity: ""`
- **THEN** validation SHALL fail with a message naming that charger and the missing `switch_entity`

#### Scenario: Settings editor blocks save
- **WHEN** a user sets a charger to type current and leaves the charging-control entity empty
- **THEN** the editor SHALL show the field as required and SHALL not allow saving
