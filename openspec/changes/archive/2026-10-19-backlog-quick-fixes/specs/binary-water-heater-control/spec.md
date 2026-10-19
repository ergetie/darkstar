## MODIFIED Requirements

### Requirement: Water heater control type is configurable and reaches the executor

Each water heater SHALL declare its control type in `water_heaters[].control_type`, with the value `"switch"` meaning the heater is driven by switching an ON/OFF entity and `"temperature"` meaning it is driven by writing a target temperature. An absent or unrecognised value SHALL be derived from the `target_entity` domain (`switch.`/`input_boolean.` give `"switch"`; `number.`/`input_number.` give `"temperature"`), and SHALL mean `"temperature"` only when the entity domain is not recognised. The executor's per-device water heater configuration SHALL carry the control type, so the value declared in configuration determines which write path is used at execution time.

The existing `water_heaters[].type` field SHALL continue to describe only the load model (`"binary"` / `"modulating"`) and SHALL NOT be read as a control type, since it defaults to `"binary"` on every heater including temperature-controlled ones.

#### Scenario: Switch control type reaches the executor
- **GIVEN** a water heater configured with `control_type: "switch"` and `target_entity: "switch.vvb"`
- **WHEN** the executor configuration is loaded
- **THEN** that heater's executor device config SHALL record switch control
- **AND** the heater SHALL be included in the per-device control loop

#### Scenario: Absent control_type is inferred from the entity domain
- **GIVEN** a water heater configured with `target_entity: "number.vvb_target"` and no `control_type` field
- **WHEN** the executor configuration is loaded
- **THEN** that heater SHALL be treated as temperature-controlled
- **AND** its execution behavior SHALL be unchanged from a heater that declares `control_type: "temperature"` explicitly

#### Scenario: Existing load-model type does not imply switch control
- **GIVEN** a water heater configured with `type: "binary"`, no `control_type`, and `target_entity: "input_number.vvbtemp"`
- **WHEN** the executor configuration is loaded
- **THEN** that heater SHALL be treated as temperature-controlled
- **AND** its `type` SHALL continue to be used only for load modelling

#### Scenario: Mixed control types in one system
- **GIVEN** heater A is `control_type: "switch"` and heater B is temperature-controlled
- **WHEN** the executor configuration is loaded
- **THEN** each heater SHALL carry its own control type independently

### Requirement: Control entity is validated against the declared control type

Configuration save SHALL reject a water heater whose `target_entity` domain cannot be written by its explicitly declared control type. When `control_type` is absent, it SHALL be derived from the entity domain and written back to the saved data, and only an unsupported domain (e.g. `climate.`, `water_heater.`) SHALL be rejected, with a message listing the supported domains. A heater with `control_type: "temperature"` SHALL require a `number.` or `input_number.` entity; a heater with `control_type: "switch"` SHALL require a `switch.` or `input_boolean.` entity. A mismatch SHALL be reported with `severity: "error"`, and the message SHALL name the control type that would accept the entity the user entered.

#### Scenario: Switch entity on a temperature heater is rejected
- **GIVEN** a water heater with `control_type: "temperature"` and `target_entity: "switch.vvb"`
- **WHEN** the configuration is saved
- **THEN** validation SHALL report an error for that heater, including its index
- **AND** the message SHALL indicate that `switch.vvb` requires `control_type: "switch"`

#### Scenario: Missing control type is derived on save
- **GIVEN** a water heater with `target_entity: "switch.vvb"` and no `control_type`
- **WHEN** the configuration is saved
- **THEN** the save SHALL succeed and the saved heater SHALL have `control_type: "switch"`

#### Scenario: Unsupported domain
- **GIVEN** a water heater with `target_entity: "climate.x"` or `"water_heater.x"`
- **WHEN** the configuration is saved
- **THEN** validation SHALL report an error listing the supported domains

#### Scenario: Number entity on a binary heater is rejected
- **GIVEN** a water heater with `control_type: "switch"` and `target_entity: "number.vvb_target"`
- **WHEN** the configuration is saved
- **THEN** validation SHALL report an error for that heater

#### Scenario: Matching entity and type is accepted
- **GIVEN** a water heater with `control_type: "switch"` and `target_entity: "switch.vvb"`
- **WHEN** the configuration is saved
- **THEN** validation SHALL report no issue for that heater's control entity

#### Scenario: Power sensor remains optional
- **GIVEN** a binary water heater with a valid `target_entity` and no `sensor` configured
- **WHEN** the configuration is saved
- **THEN** validation SHALL NOT report an error for the missing power sensor
- **AND** the heater SHALL still be controllable

## ADDED Requirements

### Requirement: Settings UI sets control type from the target entity
When a water heater's `target_entity` is selected in the settings UI, the control type SHALL be set automatically from the domain. Changing the control type manually SHALL clear a target entity of the wrong domain.

#### Scenario: Selecting a switch entity
- **WHEN** the user selects `switch.vvb` for a heater
- **THEN** control type becomes `switch` and the form can be saved

### Requirement: Mismatch errors are shown inline per heater
A save rejected for a heater's control type or entity SHALL display the message beside that heater's fields in the Heating tab and flag the tab; the Heating tab SHALL stay reachable.

#### Scenario: Explicit mismatch shown inline
- **WHEN** control type is explicitly `temperature` and the entity is `switch.vvb` and the user saves
- **THEN** the save is rejected with HTTP 400 and the message is displayed inline on that heater
