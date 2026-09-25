## Purpose

A single shared reader for an EV charger's live state of charge and plug state, reporting unreadable values as unknown and feeding the last-known plug state.

## Requirements

### Requirement: One reader for a charger's live SoC and plug state
The system SHALL provide one shared reader that returns a charger's live SoC (`float` or none) and plug state (`plugged`, `unplugged` or `unknown`). The manual-charge start API and the executor's manual-charge end check SHALL both obtain SoC and plug state only through this reader.

#### Scenario: Normal readings
- **GIVEN** the SoC sensor reads `63.5` and the plug sensor reads `connected`, which is in the charger's plugged-in states
- **WHEN** the reader runs
- **THEN** it SHALL return SoC 63.5 and plug `plugged`

#### Scenario: Car disconnected
- **GIVEN** the plug sensor reads `disconnected`, which is not in the charger's plugged-in states
- **WHEN** the reader runs
- **THEN** it SHALL return plug `unplugged`

#### Scenario: Both callers agree
- **GIVEN** identical raw sensor states
- **WHEN** the start API path and the executor end-check path read them
- **THEN** both SHALL get the same SoC and plug state

### Requirement: Unreadable values are reported as unknown
The reader SHALL return SoC as none when the SoC sensor is not configured, its state is `unavailable`/`unknown`/missing, it is non-numeric, or the read fails. It SHALL return plug `unknown` when the plug state is `unavailable`/`unknown`/missing or the read fails. It SHALL NOT substitute a last known plug reading.

#### Scenario: Plug sensor unavailable
- **GIVEN** the plug sensor state is `unavailable` and the last known reading was plugged in
- **WHEN** the reader runs
- **THEN** it SHALL return plug `unknown`

#### Scenario: Non-numeric SoC
- **GIVEN** the SoC sensor state is `n/a`
- **WHEN** the reader runs
- **THEN** it SHALL return SoC none

#### Scenario: Read error
- **GIVEN** reading the plug sensor raises an error
- **WHEN** the reader runs
- **THEN** it SHALL return plug `unknown` and log a warning

### Requirement: Charger without a plug sensor is assumed plugged in
When a charger has no plug sensor configured, the reader SHALL return plug `plugged`, matching the planner's assumption.

#### Scenario: No plug sensor
- **GIVEN** a charger with no `plug_sensor`
- **WHEN** the reader runs
- **THEN** it SHALL return plug `plugged`

### Requirement: Valid plug readings feed the last-known plug state
Every valid (`plugged` or `unplugged`) plug reading taken by the reader SHALL be recorded as the charger's last known plug state, which the dashboard uses while a charger is unreachable.

#### Scenario: Reading recorded
- **GIVEN** the plug sensor reads `connected`
- **WHEN** the reader runs
- **THEN** the charger's last known plug state SHALL be plugged in
