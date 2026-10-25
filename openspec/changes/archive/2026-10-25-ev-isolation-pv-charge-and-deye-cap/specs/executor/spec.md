## MODIFIED Requirements

### Requirement: Default self_consumption fallback allows PV charging

When the controller selects `self_consumption` and the slot plans no export (`export_kw <= 0`), `charge_value` SHALL be the configured maximum charge (`max_charge_a` or `max_charge_w` per `control_unit`), not 0 or the planned charge, so all PV can charge the battery, including the default fallback. When the slot plans PV surplus export (`charge_kw > 0`, `export_kw > 0`, `discharge_kw = 0`) or the mode is `charge`, `charge_value` SHALL stay the planned value.

#### Scenario: Default self_consumption with no planned charge

- **WHEN** the controller evaluates a slot where `charge_kw = 0`, `export_kw = 0`, `discharge_kw = 0`
- **AND** the battery SoC is above the plan target
- **AND** no EV charging is active
- **THEN** the mode intent SHALL be `"self_consumption"`
- **AND** `charge_value` SHALL equal the user's configured `max_charge_a` (or `max_charge_w` for watt-based control)
- **AND** `write_charge_current` SHALL be `True`

#### Scenario: Planned PV charge without export uses max charge

- **WHEN** the controller evaluates a slot where `charge_kw > 0`, `grid_charge_kw = 0`, `export_kw = 0`, `discharge_kw = 0` and no EV isolation is active
- **THEN** the mode intent SHALL be `"self_consumption"`
- **AND** `charge_value` SHALL equal the user's configured `max_charge_a` (or `max_charge_w`)
- **AND** `write_charge_current` SHALL be `True`

#### Scenario: Planned PV surplus still uses planned charge value

- **WHEN** the controller evaluates a slot where `charge_kw > 0` and `export_kw > 0` and `discharge_kw = 0`
- **THEN** the mode intent SHALL be `"self_consumption"`
- **AND** `charge_value` SHALL be the computed planned charge value from `_calculate_charge_limit`
- **AND** `charge_value` SHALL NOT be overridden to the user's max

#### Scenario: Default self_consumption with watt-based control unit

- **WHEN** the controller evaluates a slot with the default self_consumption fallback
- **AND** the profile's `control_unit` is `"W"`
- **THEN** `charge_value` SHALL equal the user's configured `max_charge_w`

#### Scenario: Grid charge mode keeps the planned charge value

- **WHEN** the controller selects `charge` for a slot with positive grid-charging intent (or unknown intent with zero export)
- **THEN** `charge_value` SHALL be the planned value from `_calculate_charge_limit`, not the user's max

### Requirement: Normal battery charge mode follows planned source intent

In normal planned operation, positive total battery charging with explicit zero grid-charging intent SHALL select `self_consumption` (or `idle` under EV source isolation), whether export is positive or zero. Positive grid-charging intent SHALL select `charge` unless the higher-priority battery-export condition applies. This rule SHALL NOT replace explicit runtime override decisions.

#### Scenario: Solar charging consumes all surplus
- **WHEN** a normal slot plans 3 kW total battery charging, zero grid charging, and zero export
- **THEN** the controller SHALL select `self_consumption`
- **AND** it SHALL NOT select the profile's grid-charge mode

#### Scenario: Solar charging leaves export surplus
- **WHEN** a normal slot plans 3 kW total battery charging, zero grid charging, and 1 kW export without battery discharge
- **THEN** the controller SHALL select `self_consumption`

#### Scenario: Solar charging during EV isolation
- **WHEN** a slot plans 3 kW total battery charging with zero grid charging and EV source isolation is active
- **THEN** the controller SHALL select `idle`
- **AND** it SHALL NOT select the profile's grid-charge mode

#### Scenario: Mixed or grid-only charging remains enabled
- **WHEN** a normal slot plans 3 kW total battery charging, positive grid-charging intent, and no battery export
- **THEN** the controller SHALL select `charge`

#### Scenario: Planned battery export retains priority
- **WHEN** a slot satisfies the existing battery-export condition with positive battery discharge and positive export
- **THEN** the controller SHALL select `export` before applying charge-source selection

#### Scenario: Explicit charge override remains effective
- **WHEN** an explicit runtime override requests battery charging while the underlying schedule has zero grid-charging intent
- **THEN** the controller SHALL follow the explicit override according to existing override behavior

### Requirement: EV battery source isolation preserves charging intent

When EV source isolation rebuilds a slot to block battery discharge, it SHALL preserve the original planned grid-charging intent, including explicit zero and unknown values. Blocking discharge SHALL NOT turn solar-only charging into grid charging.

#### Scenario: EV isolation preserves solar-only charging
- **WHEN** EV isolation is active for a slot with positive total battery charging and explicit zero grid charging
- **THEN** the adjusted slot SHALL retain zero grid-charging intent
- **AND** normal mode selection SHALL be `idle` (battery discharge blocked, PV charging still permitted by the profile's idle actions), not `charge`

#### Scenario: EV isolation preserves planned grid charging
- **WHEN** EV isolation is active for a slot with positive total battery charging and positive grid-charging intent
- **THEN** the adjusted slot SHALL retain that intent
- **AND** normal mode selection SHALL remain `charge`
