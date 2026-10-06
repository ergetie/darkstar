## ADDED Requirements

### Requirement: Planned battery charging retains separate grid-charging intent

The executor SHALL represent total battery charging separately from planned grid-charging intent. It SHALL preserve explicit zero rather than treating it as missing. Schedule parsing SHALL prefer non-null schedule `charge_kw`; otherwise it SHALL derive intent from non-null `grid_import_kw`, capped by total battery charging, or from non-null `import_kwh` using the existing 15-minute slot convention and the same cap. When all supported source fields are absent or null, intent SHALL remain unknown.

#### Scenario: Explicit zero takes precedence over import fallback
- **WHEN** a slot has `battery_charge_kw = 3`, `charge_kw = 0`, and `grid_import_kw = 2`
- **THEN** parsed total battery charging SHALL be 3 kW
- **AND** parsed grid-charging intent SHALL be zero

#### Scenario: Grid import power provides fallback intent
- **WHEN** a slot has total battery charging of 3 kW, no non-null `charge_kw`, and `grid_import_kw = 5`
- **THEN** parsed grid-charging intent SHALL be capped at 3 kW

#### Scenario: Grid import energy provides fallback intent
- **WHEN** a 15-minute slot has total battery charging of 3 kW, no non-null power source fields, and `import_kwh = 0.25`
- **THEN** parsed grid-charging intent SHALL be 1 kW

#### Scenario: Null source fields do not erase a usable fallback
- **WHEN** a slot has total battery charging of 3 kW, `charge_kw = null`, and `grid_import_kw = 0`
- **THEN** parsed grid-charging intent SHALL be zero

### Requirement: Normal battery charge mode follows planned source intent

During normal planned operation, positive total battery charging with explicit zero grid-charging intent SHALL select `self_consumption`, regardless of whether solar export is positive or zero. Positive total battery charging with positive grid-charging intent SHALL select `charge`, unless the existing higher-priority battery-export condition applies. This source-selection rule SHALL NOT replace explicit runtime override decisions.

#### Scenario: Solar charging consumes all surplus
- **WHEN** a normal slot plans 3 kW total battery charging, zero grid charging, and zero export
- **THEN** the controller SHALL select `self_consumption`
- **AND** it SHALL NOT select the profile's grid-charge mode

#### Scenario: Solar charging leaves export surplus
- **WHEN** a normal slot plans 3 kW total battery charging, zero grid charging, and 1 kW export without battery discharge
- **THEN** the controller SHALL select `self_consumption`

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
- **AND** normal mode selection SHALL remain `self_consumption`

#### Scenario: EV isolation preserves planned grid charging
- **WHEN** EV isolation is active for a slot with positive total battery charging and positive grid-charging intent
- **THEN** the adjusted slot SHALL retain that intent
- **AND** normal mode selection SHALL remain `charge`

### Requirement: Source-less schedules retain legacy charge selection

For schedules with no supported non-null charging-source fields, the executor SHALL retain unknown source intent and existing mode-selection behavior: positive battery charging with zero export selects `charge`, while positive charging with export and no discharge selects `self_consumption`.

#### Scenario: Legacy charge slot remains compatible
- **WHEN** a schedule contains positive `battery_charge_kw`, zero export, and no charging-source fields
- **THEN** source intent SHALL remain unknown
- **AND** the controller SHALL retain `charge` selection

#### Scenario: Legacy solar-surplus slot remains compatible
- **WHEN** a source-less schedule contains positive battery charging, positive export, and no discharge
- **THEN** the controller SHALL retain `self_consumption` selection

### Requirement: Charging-source acceptance includes planner and profile boundaries

Automated regression coverage SHALL verify the charging-source distinction through planner output formatting, executor parsing, mode selection, and the resulting profile actions for Fronius and Deye. Controller-only tests SHALL NOT be treated as proof of physical inverter behavior or financial savings.

#### Scenario: Zero-import planner output reaches the executor unchanged
- **WHEN** a planner result charges the battery with zero grid import and zero export and passes through schedule formatting and parsing
- **THEN** the executor SHALL retain explicit zero grid-charging intent and select `self_consumption`

#### Scenario: Fronius solar-only plan avoids forced grid charge
- **WHEN** normal mode selection receives an explicit solar-only charging plan with the Fronius profile
- **THEN** profile action coverage SHALL verify `Auto` selection rather than `Charge from Grid`

#### Scenario: Deye solar-only plan disables grid charging
- **WHEN** normal mode selection receives an explicit solar-only charging plan with the Deye profile
- **THEN** profile action coverage SHALL verify that `grid_charging_enable` is commanded off
