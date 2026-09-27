## ADDED Requirements

### Requirement: Commanded phase switches get a 60 s grace window

For 60 s after the executor commands a phase-mode change on a charger, zero-power ticks SHALL NOT increment the charge-failure counter. The counter SHALL NOT be reset by the grace window; counting resumes after it ends.

#### Scenario: Switch-over pause is not a failure
- **WHEN** the executor switches the charger to 3-phase at 12:00:50
- **AND** actual EV power is below 0.1 kW from 12:00:55 to 12:01:15
- **THEN** no failure notification SHALL be sent and no failure replan SHALL be requested

#### Scenario: Real failure after a switch is still detected
- **WHEN** the executor switches phase mode and actual EV power stays below 0.1 kW for 90 s
- **THEN** the failure SHALL be reported once 5 zero-power ticks have been counted after the 60 s window

#### Scenario: Counter is paused, not reset
- **WHEN** 3 zero-power ticks were counted and then a phase switch is commanded
- **AND** power stays at zero through and after the 60 s window
- **THEN** the failure SHALL fire after 2 more zero-power ticks following the window
