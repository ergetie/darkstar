## Purpose

Defines manual EV charging per charger: starting, current selection, keep-on through the plan, safety precedence, automatic end, restart persistence, status exposure, and UI.

## Requirements

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

### Requirement: Charging current for manual charge
For a `type: current` charger the manual charge SHALL request `max_current_a`, unless the user supplied a current, which SHALL be accepted only within `min_current_a`–`max_current_a`. For a `type: binary` charger the manual charge SHALL only switch the charger on, and a supplied current SHALL be rejected.

#### Scenario: Default current
- **GIVEN** a current-type charger with `max_current_a: 16`
- **WHEN** a manual charge starts without a current
- **THEN** the charger SHALL be requested at 16 A

#### Scenario: User-chosen current
- **GIVEN** a current-type charger with limits 6–16 A
- **WHEN** a manual charge starts with current 10 A
- **THEN** the charger SHALL be requested at 10 A

#### Scenario: Current rejected for binary charger
- **GIVEN** a binary charger
- **WHEN** a manual charge is requested with a current
- **THEN** the request SHALL be rejected

### Requirement: Manual charge keeps the charger on through the plan
While a manual charge is active, the executor SHALL treat the charger as "should be on" at every EV decision site regardless of the plan, and SHALL NOT switch it off because no charging is planned. Surplus-charging targets SHALL NOT lower the manual charge's requested current.

#### Scenario: No planned charging
- **GIVEN** a manual charge is active and the current slot plans 0 kW for that charger
- **WHEN** the executor tick runs
- **THEN** the charger SHALL be on (binary) or set to the manual current (current-type)

#### Scenario: Other chargers unaffected
- **GIVEN** two chargers and a manual charge only on `ev_charger_1`
- **WHEN** the executor tick runs
- **THEN** `ev_charger_2` SHALL follow the plan

### Requirement: Safety limits keep precedence over manual charge
The load balancer SHALL still throttle or pause a manually charged current-type charger, a load-balancer shed SHALL still switch off a manually charged binary charger, and the `force_stop` quick action and executor pause (manual override) SHALL still prevent charging. None of these SHALL end the manual charge by themselves.

#### Scenario: Balancer throttles
- **GIVEN** a manual charge at 16 A and phase headroom allowing only 10 A
- **WHEN** the executor tick runs
- **THEN** the charger SHALL be set to at most the balancer's limit
- **AND** the manual charge SHALL remain active

#### Scenario: Binary charger shed
- **GIVEN** a manually charged binary charger declared as a shed load
- **WHEN** the balancer sheds it
- **THEN** the charger SHALL be switched off while shed and back on when restored, while the manual charge is still active

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

### Requirement: Manual charge does not change the charging goal
Starting, running or ending a manual charge SHALL NOT modify the charger's saved goal (target SoC, ready-by, repeat, keep-on-after-target).

#### Scenario: Goal preserved
- **GIVEN** a goal of 80% by 07:00
- **WHEN** a manual charge to 60% runs and ends
- **THEN** the goal SHALL still be 80% by 07:00

### Requirement: Manual charge survives restart
Active manual charges SHALL be persisted so that an executor or container restart resumes them with the same target, current and start time.

#### Scenario: Restart mid-charge
- **GIVEN** an active manual charge to 80%
- **WHEN** the application restarts
- **THEN** the manual charge SHALL still be active with target 80%

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

### Requirement: Manual charge UI
The command bar SHALL show an EV Charge control when at least one controllable charger is plugged in, using the shared SoC stepper for the target. With more than one plugged-in controllable charger the user SHALL choose which charger; with one, no selection step SHALL be shown. For current-type chargers an optional current setting SHALL be available in the control's popover, defaulting to the charger maximum; for binary chargers it SHALL NOT be shown. While active, the control SHALL show the target and offer Stop, and the charger's EV card SHALL show "Manual charge → target%" with a Stop action.

#### Scenario: Single charger
- **GIVEN** exactly one controllable charger, plugged in
- **WHEN** the command bar renders
- **THEN** the EV Charge control SHALL be shown without a charger selector

#### Scenario: No car plugged in
- **GIVEN** no controllable charger is plugged in
- **WHEN** the command bar renders
- **THEN** the EV Charge control SHALL NOT be shown

#### Scenario: Binary charger has no current option
- **GIVEN** the selected charger is binary
- **WHEN** the EV Charge control is opened
- **THEN** no current setting SHALL be offered
