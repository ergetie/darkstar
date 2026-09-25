## MODIFIED Requirements

### Requirement: Manual charge can be started per charger
The system SHALL let the user start a manual charge on a specific EV charger with a target SoC (integer 1–100). The request SHALL be rejected when the charger id is unknown, disabled, or `externally_controlled`, when the car is not plugged in, when the car's plug state is unknown (charger unreachable or the plug read failed), when the target SoC is outside 1–100, or when the car's current SoC is unavailable or already at or above the target. SoC and plug state SHALL come from the shared live EV state reader.

#### Scenario: Start on a plugged-in car
- **GIVEN** charger `ev_charger_1` is plugged in with SoC 49%
- **WHEN** a manual charge to 80% is requested for `ev_charger_1`
- **THEN** a manual charge SHALL be active for `ev_charger_1` with target 80%

#### Scenario: Rejected when unplugged
- **GIVEN** charger `ev_charger_1` reports not plugged in
- **WHEN** a manual charge is requested
- **THEN** the request SHALL be rejected with an error saying the car is not connected

#### Scenario: Rejected when plug state is unknown
- **GIVEN** charger `ev_charger_1`'s plug sensor is `unavailable`, even though its last known reading was plugged in
- **WHEN** a manual charge is requested
- **THEN** the request SHALL be rejected with an error saying the car's plug state is unknown

#### Scenario: Rejected when already at target
- **GIVEN** the car SoC is 82%
- **WHEN** a manual charge to 80% is requested
- **THEN** the request SHALL be rejected with an error saying the target is already reached

#### Scenario: Rejected when SoC is unknown
- **GIVEN** the charger's SoC sensor is missing or unavailable
- **WHEN** a manual charge is requested
- **THEN** the request SHALL be rejected with an error saying the car SoC is unknown

### Requirement: Manual charge ends automatically
A manual charge SHALL end when the car SoC reaches or exceeds the target, when the car is reported unplugged, when the user stops it, or when a safety timeout of 24 hours since start elapses. SoC and plug state SHALL come from the shared live EV state reader. If SoC or plug state becomes unknown during a charge, charging SHALL continue until the reading returns or the timeout elapses. When a manual charge ends, the charger SHALL return to plan control on the next tick and a replan SHALL be requested (subject to the existing replan rate limit).

#### Scenario: Target reached
- **GIVEN** a manual charge to 80%
- **WHEN** the car SoC reads 80%
- **THEN** the manual charge SHALL end, the charger SHALL follow the plan, and a replan SHALL be requested

#### Scenario: Unplugged
- **GIVEN** an active manual charge
- **WHEN** the plug sensor reports not connected
- **THEN** the manual charge SHALL end

#### Scenario: Plug state unknown mid-charge
- **GIVEN** an active manual charge
- **WHEN** the plug sensor becomes `unavailable`
- **THEN** the manual charge SHALL continue

#### Scenario: Stopped by user
- **WHEN** the user stops the manual charge
- **THEN** it SHALL end immediately and the charger SHALL follow the plan on the next tick

### Requirement: Manual charge status is exposed
The EV charger API response SHALL include per charger whether a manual charge is active, its target SoC, requested current (current-type only) and start time, and a websocket event SHALL be emitted whenever a manual charge starts or ends. When an executor instance exists, the manual-charge status in the charger API SHALL come from the executor's live manual-charge state. Only when no executor instance exists SHALL it come from the persisted state file.

#### Scenario: Status after start
- **WHEN** a manual charge to 80% starts on `ev_charger_1`
- **THEN** `GET /api/ev/chargers` SHALL show `ev_charger_1` with an active manual charge and target 80%
- **AND** a manual-charge websocket event SHALL be emitted

#### Scenario: Executor and file disagree
- **GIVEN** the executor has an active manual charge on `ev_charger_1` but the state file has none (for example after a failed persist)
- **WHEN** `GET /api/ev/chargers` is called
- **THEN** `ev_charger_1` SHALL show the executor's active manual charge

#### Scenario: No executor
- **GIVEN** no executor instance exists and the state file holds a manual charge for `ev_charger_1`
- **WHEN** `GET /api/ev/chargers` is called
- **THEN** `ev_charger_1` SHALL show the manual charge from the state file
