## Purpose

The executor SHALL control water heaters during scheduled operation, ensuring proper integration with the execution history and respecting system configuration and shadow mode settings.

## Requirements

### Requirement: Executor sets water heater temperature during scheduled operation

The executor SHALL control each water heater based on the controller decision during each tick execution. For each enabled heater with a `target_entity`, the executor SHALL independently determine the temperature from the per-device plan. A temperature-controlled heater SHALL have that temperature written to its target entity. A heater declared with binary control SHALL instead be switched ON when the determined temperature is strictly greater than `temp_off`, and OFF otherwise.

#### Scenario: Water heating is scheduled for one heater
- **GIVEN** system has `has_water_heater=true`
- **AND** heater A has a configured target entity
- **AND** current slot has heater A's planned kW > 0 in `water_heater_plans`
- **WHEN** executor tick executes
- **THEN** heater A's temperature is set to `temp_normal` (e.g., 60°C)
- **AND** action result is logged to execution history

#### Scenario: Water heating is not scheduled for a heater
- **GIVEN** system has `has_water_heater=true`
- **AND** heater B has a configured target entity
- **AND** current slot has heater B's planned kW = 0 in `water_heater_plans`
- **WHEN** executor tick executes
- **THEN** heater B's temperature is set to `temp_off` (e.g., 40°C)
- **AND** action result is logged to execution history

#### Scenario: Multiple heaters controlled in same tick
- **GIVEN** two enabled heaters with target entities
- **AND** current slot has heater A heating and heater B idle
- **WHEN** executor tick executes
- **THEN** the executor SHALL set heater A to `temp_normal` AND heater B to `temp_off`
- **AND** both action results are logged to execution history

#### Scenario: Water heater not configured
- **GIVEN** system has `has_water_heater=false`
- **OR** no water heater has a configured target entity
- **WHEN** executor tick executes
- **THEN** water temperature actions are skipped
- **AND** no error is logged

#### Scenario: Binary heater is switched instead of set to a temperature
- **GIVEN** system has `has_water_heater=true`
- **AND** heater C is declared with binary control and a switch target entity
- **AND** current slot has heater C's planned kW > 0 in `water_heater_plans`
- **WHEN** executor tick executes
- **THEN** heater C's switch entity SHALL be turned ON
- **AND** no temperature value SHALL be written for heater C
- **AND** action result is logged to execution history

#### Scenario: Binary and temperature heaters in the same tick
- **GIVEN** heater A is temperature-controlled and heater C is binary
- **AND** the current slot plans heating for both
- **WHEN** executor tick executes
- **THEN** heater A SHALL have `temp_normal` written to its target entity
- **AND** heater C's switch entity SHALL be turned ON
- **AND** both action results are logged to execution history

### Requirement: Water temperature action is idempotent

The executor SHALL skip controlling a heater if it is already in the required state: for a temperature-controlled heater, if the current temperature already matches the target; for a binary heater, if the switch entity is already in the required ON or OFF state.

#### Scenario: Temperature already at target for one heater
- **GIVEN** heater A's current temperature is 60°C
- **AND** controller decision sets heater A to `temp_normal=60`
- **WHEN** executor executes water temp action for heater A
- **THEN** action is skipped with `skipped=True`
- **AND** result message indicates "Already at 60°C"

#### Scenario: Binary heater already in the required state
- **GIVEN** heater C is binary and its switch entity is already `on`
- **AND** the current tick resolves heater C to ON
- **WHEN** executor executes the action for heater C
- **THEN** action is skipped with `skipped=True`
- **AND** no service call is made

### Requirement: Water temperature action respects shadow mode

The executor SHALL NOT actually control any water heater when shadow mode is enabled, for either control type.

#### Scenario: Shadow mode enabled with multiple heaters
- **GIVEN** executor is in shadow mode
- **AND** two heaters have per-device plans
- **WHEN** water temp actions would execute
- **THEN** temperatures are NOT sent to Home Assistant for either heater
- **AND** action results have `skipped=True` for each heater

#### Scenario: Shadow mode with a binary heater
- **GIVEN** executor is in shadow mode
- **AND** a binary heater's current tick resolves to ON while its switch entity is `off`
- **WHEN** the action would execute
- **THEN** no service call is sent to Home Assistant
- **AND** the action result has `skipped=True`

### Requirement: Water temperature action is logged to execution history

Each water heater action result SHALL be included in the execution history record, with the heater ID included in the action metadata. A binary heater's entry SHALL record the commanded switch state in place of a temperature.

#### Scenario: Per-device actions logged to history
- **GIVEN** two water heaters have temperature actions executed
- **WHEN** execution record is created
- **THEN** `action_results` includes entries for each heater with:
  - `type: "water_temp"`
  - `success: true/false`
  - `previous_value: <old temp>`
  - `new_value: <target temp>`
  - `entity_id: <heater's target entity>`
  - `skipped: true/false`

#### Scenario: Binary heater action logged to history
- **GIVEN** a binary heater is switched during a tick
- **WHEN** execution record is created
- **THEN** `action_results` includes an entry for that heater with:
  - `type: "water_switch"`
  - `success: true/false`
  - `previous_value: <previous switch state>`
  - `new_value: <commanded switch state>`
  - `entity_id: <heater's switch entity>`
  - `skipped: true/false`

### Requirement: Water temperature follows EV charger control pattern

Water heater control SHALL be implemented as a per-device control loop outside the inverter profile system, consistent with the EV charger per-device pattern, for both control types.

#### Scenario: Architecture alignment with per-device EV charger
- **GIVEN** executor controls multiple device types with per-device loops
- **WHEN** water heater control is executed
- **THEN** it follows the same pattern as per-device EV charger:
  - Iterates over configured heaters in `_tick()` after inverter profile execution
  - Uses `dispatcher.set_water_temp(target_entity, temp)` per heater
  - Results appended to `action_results`
  - Conditioned on `has_water_heater` and per-device entity configuration

#### Scenario: Binary heaters use the same loop
- **GIVEN** a binary heater is configured
- **WHEN** water heater control is executed
- **THEN** it SHALL be driven from the same per-device loop, dispatching an ON/OFF write instead of a temperature write
- **AND** its result SHALL be appended to the same `action_results` list

### Requirement: Executor supports boost temperature from schedule

The executor SHALL set a temperature-controlled water heater's target temperature to `temp_boost` (85°C) when the schedule indicates boost mode for that heater, instead of the normal `temp_normal` (60°C). For a binary heater, boost SHALL resolve to ON, since no boost temperature can be expressed.

#### Scenario: Water heater boost scheduled
- **WHEN** the current slot has `water_heating_boost` with heater A set to true
- **AND** heater A has a configured target entity
- **WHEN** executor tick executes
- **THEN** heater A's temperature SHALL be set to `temp_boost` (85°C)

#### Scenario: Water heater normal heating scheduled
- **WHEN** the current slot has heater A's planned kW > 0
- **AND** `water_heating_boost` does not include heater A
- **WHEN** executor tick executes
- **THEN** heater A's temperature SHALL be set to `temp_normal` (60°C)

#### Scenario: Water heater boost takes precedence over normal
- **WHEN** the current slot has heater A in both normal heating and boost
- **WHEN** executor tick executes
- **THEN** heater A's temperature SHALL be set to `temp_boost` (85°C)
- **AND** boost SHALL override the normal temperature

#### Scenario: Boost applied per-device independently
- **WHEN** the schedule has heater A in boost mode and heater B in normal mode
- **WHEN** executor tick executes
- **THEN** heater A SHALL be set to `temp_boost` (85°C)
- **AND** heater B SHALL be set to `temp_normal` (60°C)

#### Scenario: Boost on a binary heater resolves to ON
- **WHEN** the current slot has `water_heating_boost` set for a binary heater
- **WHEN** executor tick executes
- **THEN** that heater SHALL be switched ON
- **AND** no boost temperature SHALL be written for that heater
