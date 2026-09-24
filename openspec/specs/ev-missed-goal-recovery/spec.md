# Spec: EV Missed Goal Recovery

## Purpose

Defines how a missed EV charging goal stays active for a grace window while the car remains plugged in, and how an unreachable charger is distinguished from an unplugged one.

## Requirements

### Requirement: Missed goal stays active during a grace window
When a charger's goal deadline has passed, the charger is plugged in (or unreachable with last known state plugged in), and the live SoC is below `target_soc_percent`, the pipeline SHALL keep the goal active with an effective deadline of `missed_deadline + missed_goal_grace_hours`, capped at the goal's next regular ready-by. `required_kwh` SHALL be computed from live SoC as for a normal goal, and the solver SHALL schedule it in the cheapest slots within the window using the existing soft shortfall constraint. `missed_goal_grace_hours` SHALL be a per-charger `ev_chargers[]` setting defaulting to 4; `0` SHALL disable the grace window.

#### Scenario: Goal missed, car still plugged in
- **WHEN** the goal was 55% by 10:30, it is now 10:31, SoC is 53%, the car is plugged in, and grace is 4 h
- **THEN** the planner SHALL use an effective deadline of 14:30
- **AND** SHALL schedule the remaining energy in the cheapest slots before 14:30

#### Scenario: Grace window expired
- **WHEN** the deadline passed more than `missed_goal_grace_hours` ago
- **THEN** the goal SHALL resolve to its next regular ready-by (or none for one-off goals), as today

#### Scenario: Car unplugged after missed deadline
- **WHEN** the deadline passed and the charger reports unplugged
- **THEN** no grace window SHALL apply

#### Scenario: Grace disabled
- **WHEN** `missed_goal_grace_hours` is 0
- **THEN** behaviour SHALL be identical to before this change

#### Scenario: Goal set after its deadline
- **WHEN** the goal was saved (`last_updated`) after the deadline it would have missed
- **THEN** no grace window SHALL apply, because that deadline was never a goal the planner pursued

#### Scenario: Grace capped by next ready-by
- **WHEN** the grace window would end after the goal's next regular ready-by
- **THEN** the effective deadline SHALL be the next regular ready-by

### Requirement: Unreachable charger is distinct from unplugged
When a charger's plug sensor or switch entity reads `unavailable` or `unknown`, the system SHALL classify the charger as unreachable, not unplugged. An unreachable charger SHALL keep its last known plug state for planning, SHALL NOT trigger an unplug replan, and SHALL be reported as unreachable in logs, the EV API and the dashboard EV card. When the entity returns to a valid state, normal plug-in/unplug handling SHALL apply.

#### Scenario: Charger drops off HA mid-session
- **WHEN** a plugged-in charger's plug sensor becomes `unavailable`
- **THEN** the system SHALL log the charger as unreachable
- **AND** SHALL NOT trigger an unplug replan
- **AND** the EV API SHALL report `unreachable: true` for that charger

#### Scenario: Charger returns
- **WHEN** an unreachable charger's plug sensor returns to a connected state
- **THEN** a plug-in replan SHALL be triggered per existing replan rules
