# battery-power-limits Specification

## Purpose
Define one unit-aware meaning of the battery maximum charge and discharge power, so the solver, manual plans, preflight, onboarding and settings never disagree about it.

## Requirements

### Requirement: Single resolved battery power limit
The system SHALL resolve the battery maximum charge and discharge power in kW from the active control unit (`executor.inverter.control_unit`, default Amps), using only that unit's fields. Watts mode SHALL use `battery.max_*_w`; Amps mode SHALL use `battery.max_*_a` times the nominal battery voltage (48 V when unset). A missing limit SHALL resolve to 0 kW.

#### Scenario: Amps mode
- **WHEN** the control unit is Amps, `max_charge_a` is 100 and `nominal_voltage_v` is 48
- **THEN** the resolved charge limit is 4.8 kW regardless of any `max_charge_w` value

#### Scenario: Watts mode
- **WHEN** the control unit is Watts and `max_charge_w` is 5000
- **THEN** the resolved charge limit is 5.0 kW regardless of any `max_charge_a` value

#### Scenario: Limit missing
- **WHEN** the active unit's charge field is absent
- **THEN** the resolved charge limit is 0 kW

### Requirement: All consumers share the resolved limit
The solver, manual plans and preflight SHALL all use the same resolved limit; no code path SHALL read any other key for the battery power limit.

#### Scenario: Consistent value
- **WHEN** the planner, a manual Charge entry and preflight run on the same config
- **THEN** all three use the same resolved kW value

### Requirement: Manual charge uses the resolved limit
A manual plan "Charge" entry SHALL schedule charging at the resolved maximum charge power. It SHALL NOT read `battery.max_charge_power_kw`.

#### Scenario: Amps-mode config without the stray key
- **WHEN** the control unit is Amps with `max_charge_a` 100 at 48 V and a manual Charge entry covers a slot
- **THEN** the slot's `charge_kw` is 4.8

#### Scenario: Stray key present
- **WHEN** a config still contains `battery.max_charge_power_kw: 8` and the resolved limit is 5 kW
- **THEN** a manual Charge slot is planned at 5 kW

#### Scenario: Limit not configured
- **WHEN** the resolved charge limit is 0 kW
- **THEN** the manual Charge slot is planned at 0 kW and a warning is logged

### Requirement: Onboarding collects the active unit's limits
The onboarding battery step SHALL ask for and require the max charge and discharge values of the active control unit only: current in Amps (plus nominal voltage) for Amps profiles, power in Watts for Watts profiles. The active unit is the selected inverter profile's control unit, else the configured control unit, else Amps. Step completeness and the saved patch SHALL cover only the active pair.

#### Scenario: Amps profile
- **WHEN** the selected profile uses Amps
- **THEN** the step shows max charge/discharge current and nominal voltage, does not show Watts fields, and is complete once those are positive

#### Scenario: Watts profile
- **WHEN** the selected profile uses Watts
- **THEN** the step shows max charge/discharge power in Watts and is complete once both are positive, without requiring any Amps value

### Requirement: Settings describe and preview the limit
The battery settings fields SHALL describe max charge/discharge as the battery's maximum charge/discharge current or power, and the Amp fields SHALL show a read-only effective power hint (amps x nominal voltage, 48 V when unset) while the value is positive.

#### Scenario: Effective kW hint
- **WHEN** Amps mode is active, `max_charge_a` is 100 and nominal voltage is 48
- **THEN** the field shows "~4.80 kW at 48 V"

#### Scenario: Empty value
- **WHEN** the amps field is empty
- **THEN** no hint is shown
