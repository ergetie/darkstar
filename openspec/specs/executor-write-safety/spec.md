# Executor Write Safety

## Purpose
Ensure executor writes to Home Assistant respect entity limits, are logged without spam, and report failures with actionable error text.

## Requirements
### Requirement: Numeric writes respect entity min, max and step
Before writing to a `number` or `input_number` entity the executor SHALL clamp the value to the entity's `min` and `max` attributes and snap it to its `step`, using the entity state fetched for that write. With no usable attributes the value SHALL be written unchanged.

#### Scenario: Snapping rules
- **WHEN** a step is present
- **THEN** snapping is relative to `min` (or 0), rounds to the nearest step, and never leaves `[min, max]`
- **AND** a non-finite value is written unchanged

#### Scenario: Clamp precedes skip checks
- **WHEN** the entity is already at its limit
- **THEN** the clamp is applied before the "already at value" and deadband checks, so it is not rewritten every tick

#### Scenario: Value above entity max
- **WHEN** the resolved value is 18200 and the entity has `max` 17500
- **THEN** 17500 is written and the `ActionResult.new_value` is 17500

#### Scenario: Negative range
- **WHEN** the entity has `min` -17500, `max` 17500, `step` 100 and the resolved value is -18000
- **THEN** -17500 is written

#### Scenario: Step snapping from min
- **WHEN** the entity has `min` 50, `max` 1000, `step` 100 and the resolved value is 430
- **THEN** 450 is written

#### Scenario: Rounding would exceed max
- **WHEN** the entity has `min` 0, `max` 1050, `step` 100 and the resolved value is 1040
- **THEN** 1000 is written

#### Scenario: Attributes missing or unavailable
- **WHEN** the entity state is `unavailable`, or has no `min`/`max`/`step` attributes, or `step` is `any`
- **THEN** the value is written as before, with only the usable bounds applied

#### Scenario: Entity already at its limit
- **WHEN** the clamped value equals the entity's current state
- **THEN** the action is skipped as "Already at" and no service call is made

### Requirement: Clamping is logged without spam
When a value is changed by the entity-range clamp the executor SHALL log it once per entity per hour at warning level (naming the entity, requested value, written value and the limit applied) and at debug level otherwise. The `ActionResult.message` of a clamped write SHALL state the requested value.

#### Scenario: Repeated clamping
- **WHEN** the same entity is clamped on 12 consecutive ticks within one hour
- **THEN** exactly one warning is logged for that entity in that hour

### Requirement: Export power templates are clamped to max discharge power
The controller SHALL clamp `export_power_w` and `export_with_load_w` to the configured maximum discharge power in watts before building the decision: `max_discharge_w` when the active control unit is W, otherwise `max_discharge_a` times `nominal_voltage_v`. `export_with_load_w` SHALL be clamped after step rounding. A non-positive configured maximum SHALL disable the clamp.

#### Scenario: Export plus load exceeds the maximum
- **WHEN** export is 12 kW, load 6 kW and `max_discharge_w` is 17500
- **THEN** `export_with_load_w` is 17500

#### Scenario: Ampere control unit
- **WHEN** the control unit is A, `max_discharge_a` is 40 and `nominal_voltage_v` is 230
- **THEN** `export_power_w` is at most 9200

#### Scenario: No export
- **WHEN** `slot.export_kw` is 0
- **THEN** both values are 0

### Requirement: Failed profile actions carry the HA error text
When a profile action write raises `HACallError`, the resulting `ActionResult` SHALL have `error_details` set to the error text and a message of the form `Failed to set <entity>: <error text>`. `ActionResult.ha_unavailable` SHALL be true when the error has no HTTP status (connection error, timeout or retries exhausted).

#### Scenario: HA rejects a write
- **WHEN** HA returns HTTP 400 with a body for `input_number.darkstar_power_rec_w`
- **THEN** `error_details` contains "HTTP 400" and the response body

#### Scenario: HA unreachable
- **WHEN** the write fails after all retries without an HTTP status
- **THEN** `ha_unavailable` is true
