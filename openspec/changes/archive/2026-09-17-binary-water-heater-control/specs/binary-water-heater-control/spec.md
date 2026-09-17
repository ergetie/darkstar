Throughout this capability, "binary heater" means a water heater whose **`control_type` is `"switch"`**. It does not refer to the separate load-model field `type: "binary"`, which describes how the load draws power and applies to most temperature-controlled heaters too.

## ADDED Requirements

### Requirement: Water heater control type is configurable and reaches the executor

Each water heater SHALL declare its control type in `water_heaters[].control_type`, with the value `"switch"` meaning the heater is driven by switching an ON/OFF entity and `"temperature"` meaning it is driven by writing a target temperature. An absent or unrecognised value SHALL mean `"temperature"`. The executor's per-device water heater configuration SHALL carry the control type, so the value declared in configuration determines which write path is used at execution time.

The existing `water_heaters[].type` field SHALL continue to describe only the load model (`"binary"` / `"modulating"`) and SHALL NOT be read as a control type, since it defaults to `"binary"` on every heater including temperature-controlled ones.

#### Scenario: Switch control type reaches the executor
- **GIVEN** a water heater configured with `control_type: "switch"` and `target_entity: "switch.vvb"`
- **WHEN** the executor configuration is loaded
- **THEN** that heater's executor device config SHALL record switch control
- **AND** the heater SHALL be included in the per-device control loop

#### Scenario: Absent control_type defaults to temperature control
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

### Requirement: Binary heaters translate planned temperature to ON or OFF

For a binary heater, the executor SHALL translate the temperature resolved for that heater in the current tick into a switch state: ON when the resolved temperature is strictly greater than `temp_off`, and OFF otherwise. The planner, the controller, and the per-device schedule SHALL continue to express water heating in kW and temperatures for every heater regardless of control type.

#### Scenario: Scheduled heating switches the heater on
- **GIVEN** a binary heater with `target_entity: "switch.vvb"`
- **AND** the current slot plans heating for that heater, resolving to `temp_normal`
- **WHEN** the executor tick executes
- **THEN** the executor SHALL turn `switch.vvb` ON
- **AND** the action result SHALL be logged to execution history

#### Scenario: Idle slot switches the heater off
- **GIVEN** a binary heater with `target_entity: "switch.vvb"`
- **AND** the current slot plans no heating for that heater, resolving to `temp_off`
- **WHEN** the executor tick executes
- **THEN** the executor SHALL turn `switch.vvb` OFF

#### Scenario: Boost temperature also resolves to ON
- **GIVEN** a binary heater whose resolved temperature for the current tick is `temp_boost`
- **WHEN** the executor tick executes
- **THEN** the executor SHALL turn the heater ON
- **AND** the executor SHALL NOT write any temperature value to Home Assistant for that heater

#### Scenario: Load-balancer shed switches the heater off
- **GIVEN** a binary heater that the load balancer has selected to shed
- **WHEN** the executor tick executes
- **THEN** the shed SHALL resolve that heater to `temp_off`
- **AND** the executor SHALL turn the heater OFF

#### Scenario: Temperature values are never written for a binary heater
- **GIVEN** a binary heater with `temp_normal: 60` and `temp_boost: 85` present in configuration
- **WHEN** the executor controls that heater in any tick
- **THEN** no `number` or `input_number` service call SHALL be made for that heater

### Requirement: Binary heater writes are idempotent and respect shadow mode

A binary heater write SHALL be skipped when the switch entity is already in the required state, and SHALL NOT reach Home Assistant when the executor is in shadow mode. In both cases the executor SHALL return an action result marked as skipped.

#### Scenario: Heater already in the required state
- **GIVEN** a binary heater whose switch entity is already `on`
- **AND** the current tick resolves that heater to ON
- **WHEN** the executor tick executes
- **THEN** no service call SHALL be made
- **AND** the action result SHALL be marked skipped

#### Scenario: Shadow mode does not write
- **GIVEN** the executor is in shadow mode
- **AND** a binary heater's current tick resolves to ON while its switch entity is `off`
- **WHEN** the executor tick executes
- **THEN** no service call SHALL be made
- **AND** the action result SHALL be marked skipped

### Requirement: Binary heater actions are recorded in execution history under a distinct action type

Each binary heater action SHALL produce an action result recorded in the execution history with the action type `water_switch`, carrying the heater's switch entity id, the previous state, the commanded state, and whether the action was skipped, so a binary heater's execution is auditable in the same way as a temperature-controlled one. Every consumer that treats `water_temp` as "water heating" SHALL also recognise `water_switch`.

#### Scenario: Binary action appears in the execution record
- **GIVEN** a binary heater is switched from `off` to `on` during a tick
- **WHEN** the execution record for that tick is created
- **THEN** `action_results` SHALL include an entry for that heater with `type: "water_switch"`, its `entity_id`, previous state, new state, and `skipped: false`

#### Scenario: Binary heater is distinguishable from other switched loads
- **GIVEN** the same tick switches both a binary water heater and a load-balancer custom entity
- **WHEN** the execution record is created
- **THEN** the water heater's entry SHALL carry `type: "water_switch"`
- **AND** the custom-entity load's entry SHALL retain its own action type

#### Scenario: History views count binary heaters as water heating
- **GIVEN** a view or filter that selects water heating actions from execution history
- **WHEN** both a temperature heater and a binary heater have acted
- **THEN** the view SHALL include both the `water_temp` and the `water_switch` entries

### Requirement: Manual boost on a binary heater switches it on

Manual water boost SHALL resolve to ON for a binary heater for the duration of the boost, since a binary heater has no boost temperature to reach. The system SHALL NOT present a boost temperature control for a binary heater. Boost delivery itself is specified by the `per-device-water-boost` capability; this requirement covers only what boost means for a binary heater.

#### Scenario: Boost started on a binary heater
- **GIVEN** a binary heater
- **WHEN** the user starts a water boost
- **THEN** the boost SHALL resolve that heater to ON for the boost duration

#### Scenario: Boost cleared on a binary heater
- **GIVEN** a binary heater with an active boost
- **WHEN** the boost is cleared or expires
- **THEN** the heater SHALL return to the state the current schedule resolves to

#### Scenario: Boost temperature is not offered
- **GIVEN** a binary heater
- **WHEN** the water heater's settings and boost controls are rendered
- **THEN** no boost temperature, normal temperature, or idle temperature control SHALL be offered for that heater

### Requirement: Control entity is validated against the declared control type

Configuration save SHALL reject a water heater whose `target_entity` domain cannot be written by its declared control type. A heater with `control_type: "temperature"` SHALL require a `number.` or `input_number.` entity; a heater with `control_type: "switch"` SHALL require a `switch.` or `input_boolean.` entity. A mismatch SHALL be reported with `severity: "error"`, and the message SHALL name the control type that would accept the entity the user entered.

#### Scenario: Switch entity on a temperature heater is rejected
- **GIVEN** a water heater with no `control_type` (so temperature control) and `target_entity: "switch.vvb"`
- **WHEN** the configuration is saved
- **THEN** validation SHALL report an error for that heater
- **AND** the message SHALL indicate that `switch.vvb` requires `control_type: "switch"`

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

### Requirement: Mismatched configuration reaching the executor is skipped, not fatal

A water heater whose declared control type does not match its `target_entity` domain SHALL be skipped by the executor with a logged warning, in the same way a heater with no `target_entity` is skipped. The executor SHALL NOT raise, and SHALL continue controlling every other heater in the same tick.

#### Scenario: Hand-edited config with a mismatched pair
- **GIVEN** a configuration edited outside the save-time validation, pairing `control_type: "temperature"` with `target_entity: "switch.vvb"`
- **WHEN** the executor tick executes
- **THEN** the executor SHALL log a warning naming that heater
- **AND** SHALL skip control for that heater
- **AND** SHALL control all other configured heaters normally

### Requirement: Settings expose the control type

The water heater settings editor SHALL let the user choose the control type per heater, and SHALL label the control entity field according to the selected type so it is clear which kind of entity is expected.

#### Scenario: Control type is selectable
- **WHEN** a user edits a water heater in settings
- **THEN** the editor SHALL offer a choice between temperature control and switch ON/OFF control, distinct from the existing load-model `type` field

#### Scenario: Entity field reflects the selected type
- **GIVEN** a user has selected binary control for a heater
- **WHEN** the control entity field is rendered
- **THEN** it SHALL indicate that a switch or input_boolean entity is expected
