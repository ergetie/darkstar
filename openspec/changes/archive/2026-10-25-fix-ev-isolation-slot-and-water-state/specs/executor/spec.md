## ADDED Requirements

### Requirement: EV source isolation preserves the slot plan
EV source isolation SHALL zero only battery discharge; every other `SlotPlan` field SHALL reach the controller unchanged. Water heaters SHALL follow their plan during isolation for every trigger.

#### Scenario: Planned EV charging with per-device water plan
- **GIVEN** a switch-controlled heater planned at 3.1 kW and planned EV charging in the same slot
- **WHEN** isolation starts
- **THEN** the heater's decision temperature SHALL be `temp_normal` and the heater switch SHALL be turned or left on

#### Scenario: Manual EV charge with water plan
- **GIVEN** an active manual EV charge and a heater planned in the slot
- **WHEN** the executor ticks
- **THEN** the heater SHALL stay on its plan

#### Scenario: Actual unplanned charging with water plan
- **GIVEN** measured EV power above 0.1 kW, no planned EV charging, and a heater planned in the slot
- **WHEN** the executor ticks
- **THEN** the heater SHALL stay on its plan

#### Scenario: All other fields preserved
- Fields include `water_heater_plans`, `water_heating_boost`, `ev_charger_plans`, `ev_surplus_kw`, `custom_entity_active`, `soc_entry`, `slot_start`, `slot_end`.
- **WHEN** isolation builds its slot from any `SlotPlan`
- **THEN** every field of `SlotPlan` except `discharge_kw` and `discharge_blocked_by_ev` SHALL equal the original's

### Requirement: Executor page shows the before-state of the water heater without a fake temperature
In "State before execution" the Executor page SHALL show a numeric temperature with `°C` only when `before_water_temp` has a value. For a switch (on/off) heater with no temperature it SHALL show the heater's switch state before execution (On or Off, from the `previous_value` of the record's `water_switch` action). When neither is available it SHALL show "—" without a unit.

#### Scenario: Switch heater
- **GIVEN** a record with `before_water_temp` null and a `water_switch` action whose `previous_value` is "off"
- **THEN** the cell SHALL show "Off" and no `°C`

#### Scenario: Temperature heater with failed read
- **GIVEN** a record with `before_water_temp` null and no `water_switch` action
- **THEN** the cell SHALL show "—" with no `°C`

#### Scenario: Temperature heater with a reading
- **GIVEN** `before_water_temp` 55.5
- **THEN** the cell SHALL show the temperature with `°C`

## MODIFIED Requirements

### Requirement: Water heater sensor reads are gated by has_water_heater flag
The executor, recorder, load disaggregator and live-power socket mapping SHALL NOT fetch, register or map water heater power sensors when `system.has_water_heater` is `false`, and the executor SHALL read a water heater's current temperature only when the flag is `true` and that heater's `control_type` is `temperature`.

#### Scenario: Missing flag is treated as enabled
- **WHEN** the `system.has_water_heater` key is absent
- **THEN** every reader, including the socket client, SHALL treat it as `true`

#### Scenario: Disabled flag skips the sensor loop entirely
- **WHEN** `system.has_water_heater` is `false`
- **THEN** the `water_heaters[]` sensor loop SHALL be skipped entirely

#### Scenario: Switch-controlled heater is never read for temperature
- **WHEN** a heater has `control_type: switch`
- **THEN** the executor SHALL NOT attempt a temperature read or parse for it

#### Scenario: current_water_temp comes from the first configured heater
- **WHEN** the executor determines its single `current_water_temp` value
- **THEN** the value SHALL be taken from the first configured heater (`water_heater_devices[0]`)
- **AND** when that heater is switch-controlled, no read occurs and `current_water_temp` stays `None` (no reading)

#### Scenario: Water heating disabled skips sensor reads
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `false`
- **THEN** no HTTP requests are made for water heater sensors
- **AND** no 404 warnings are logged for missing water heater entities

#### Scenario: Water heating enabled reads sensors normally
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `true`
- **THEN** enabled water heater sensors from `water_heaters[]` are fetched as before

#### Scenario: Switch-controlled heater
- **WHEN** a heater has `control_type: switch` and target entity state "on"
- **THEN** no temperature read or parse is attempted for it, no warning is logged, and `current_water_temp` stays `None` (no reading)

#### Scenario: Temperature-controlled heater
- **WHEN** the first heater has `control_type: temperature` and the entity state is "55.5"
- **THEN** `current_water_temp` is 55.5

#### Scenario: Mixed multi-device setup
- **WHEN** the first heater is `control_type: temperature` and a second is `control_type: switch`
- **THEN** only the first heater's temperature is read and the second heater's target entity is never parsed as a temperature

#### Scenario: Load disaggregator registers no water loads when flag off
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters[]` has an enabled heater with a sensor
- **WHEN** the recorder builds its `LoadDisaggregator`
- **THEN** no water heater load is registered and water energy is recorded as 0.0

#### Scenario: Socket client with missing flag
- **GIVEN** `system.has_water_heater` is absent
- **WHEN** the live socket client builds its sensor mapping
- **THEN** enabled heater sensors are mapped (default true)

#### Scenario: Socket client with flag off
- **GIVEN** `system.has_water_heater` is `false` with configured heaters
- **THEN** no `water_kw_*` mapping exists and `water_heater_configs` is empty

#### Scenario: Failed temperature read records no value
- **WHEN** the first heater is `control_type: temperature` and its state cannot be parsed as a number
- **THEN** `current_water_temp` SHALL stay `None` and the execution record's `before_water_temp` SHALL be `None`

#### Scenario: Switch heater records no temperature
- **WHEN** the first heater is `control_type: switch`
- **THEN** the execution record's `before_water_temp` SHALL be `None`, not a default such as 50
