## MODIFIED Requirements

### Requirement: Pipeline builds per-device mid-block locking
The pipeline SHALL detect mid-block heating state per water heater independently. For each heater currently in an active heating block (detected via power sensor), the pipeline SHALL set `force_on_slots` on that heater's `WaterHeaterInput`.

The pipeline SHALL read the previous schedule from the same path the planner writes it to, resolved from a single shared constant rather than a separately hardcoded path, so that reader and writer cannot diverge. When the previous schedule is absent, unreadable, or contains an empty slot list, the pipeline SHALL log a warning naming the path, and SHALL NOT treat that condition as evidence that no heater is mid-block.

#### Scenario: One heater mid-block, another idle
- **WHEN** heater A's power sensor shows active heating and heater B's power sensor shows idle
- **THEN** heater A's `WaterHeaterInput.force_on_slots` SHALL contain the remaining block slot indices
- **AND** heater B's `WaterHeaterInput.force_on_slots` SHALL be None or empty

#### Scenario: No heaters mid-block
- **WHEN** no heater power sensors show active heating
- **THEN** all heaters' `force_on_slots` SHALL be None or empty

#### Scenario: Previous schedule is read from the written path
- **WHEN** the pipeline loads the previous schedule for mid-block detection
- **THEN** it SHALL read the path that `save_schedule_to_json` writes
- **AND** both SHALL resolve that path from the same shared constant

#### Scenario: Missing previous schedule is reported, not silently ignored
- **WHEN** the previous schedule file does not exist, cannot be parsed, or contains an empty slot list
- **THEN** the pipeline SHALL log a warning naming the path
- **AND** SHALL NOT silently proceed as though every heater were idle

#### Scenario: Mid-block lock is observable when it fires
- **WHEN** a heater is detected mid-block and its remaining slots are forced on
- **THEN** the pipeline SHALL log the heater identifier and the number of slots locked
