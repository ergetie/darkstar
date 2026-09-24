## ADDED Requirements

### Requirement: In-progress slot uses remaining time for EV energy
When planning starts inside a slot, the solver SHALL bound that slot's EV energy by the remaining duration (`slot_end − now`), not the full slot duration, and the planned EV kW for that slot SHALL be reported as energy divided by the remaining duration. Other energy flows in the slot SHALL be unchanged.

#### Scenario: Replan 7 minutes into a slot
- **WHEN** a replan runs at 10:22 for the 10:15–10:30 slot and the goal needs 1.2 kWh by 10:30
- **THEN** the solver SHALL allow at most `max_power_kw × 8/60` kWh in that slot
- **AND** the reported kW for that slot SHALL be the planned energy divided by 8/60 h

#### Scenario: Replan at slot start
- **WHEN** a replan runs exactly at a slot boundary
- **THEN** the EV bounds SHALL be identical to before this change

### Requirement: Post-deadline charging allowed during grace window
The solver's rule forcing zero EV energy after a charger's deadline SHALL use the effective deadline, which during a missed-goal grace window (see `ev-missed-goal-recovery`) is the extended grace deadline.

#### Scenario: Charging after missed deadline
- **WHEN** a charger is in a grace window ending 14:30
- **THEN** the solver SHALL permit EV energy in slots ending at or before 14:30
