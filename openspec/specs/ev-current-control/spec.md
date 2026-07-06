# Spec: EV Current Control

## Purpose

Defines how the executor controls current-type EV chargers (ampere setpoint via an HA number entity) as an alternative to binary switch control, including kW→A translation, minimum-current pause semantics, active phase detection, and migration of the legacy singular EV charger config stub.

## Requirements

### Requirement: Current-type charger actuation
For EV charger devices configured with `type: current` and a `current_entity`, the executor SHALL control charging by writing an integer ampere setpoint to the charger's HA number entity instead of toggling a switch. The planner-derived target SHALL be computed as `floor(planned_kw × 1000 / (230 × active_phases))`, clamped to `[min_current_a, max_current_a]`. Writes SHALL be idempotent (skipped when the entity already holds the target value).

#### Scenario: Planned 11 kW on a 3-phase charger
- **WHEN** the current slot plans 11.0 kW for a 3-phase charger with `max_current_a: 16`
- **THEN** the executor SHALL write a setpoint of 15 A (floor of 11000 / 690)

#### Scenario: Setpoint unchanged between ticks
- **WHEN** the computed setpoint equals the value already set on the charger
- **THEN** no HA service call SHALL be made for that tick

### Requirement: Minimum current floor with pause semantics
The executor SHALL never write a setpoint below `min_current_a` (default 6). When the target (planned or balancer-capped) falls below the floor, the executor SHALL stop charging instead, using the charger's stop mechanism, and treat the session as paused rather than failed.

#### Scenario: Plan implies 4 A
- **WHEN** the planner-derived target computes to 4 A
- **THEN** the executor SHALL stop charging rather than write 4 A

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
