## MODIFIED Requirements

### Requirement: Minimum current floor with pause semantics
The executor SHALL never write a setpoint below `min_current_a` (default 6), and SHALL never write 0 A. Whenever charging must stop (the target, planned or balancer-capped, falls below the floor; the plan ends; a load-balancer pause; manual override or force_stop), the executor SHALL stop charging by setting the `switch_entity` to its configured `charge_disabled_value` (select-like) or `off` (switch-like). It SHALL treat the session as paused rather than failed. No value SHALL be hardcoded.

#### Scenario: Plan implies 4 A
- **WHEN** the planner-derived target computes to 4 A
- **THEN** the executor SHALL set the switch entity to the configured `charge_disabled_value` rather than write 4 A or 0 A

#### Scenario: Plan slot ends
- **WHEN** a current-type charger was charging and the new slot plans 0 kW with no keep-on flag
- **THEN** the executor SHALL set the switch entity to `charge_disabled_value`
- **AND** SHALL NOT call `number.set_value` on the current entity

### Requirement: Binary chargers remain unchanged
Devices with `type: binary` (or absent type) SHALL keep the existing ON/OFF switch behavior, per-device state tracking, and source isolation. Current-type devices SHALL retain the same source isolation semantics.

#### Scenario: Mixed fleet
- **WHEN** one charger is `type: binary` and another is `type: current`
- **THEN** the binary charger is switch-controlled and the current charger is setpoint-controlled, independently

#### Scenario: Source isolation with current control
- **WHEN** a current-type charger is actively charging at any setpoint
- **THEN** battery discharge SHALL be blocked exactly as for binary chargers
