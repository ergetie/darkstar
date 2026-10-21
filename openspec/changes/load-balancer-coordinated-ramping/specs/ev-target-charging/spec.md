## MODIFIED Requirements

### Requirement: In-progress slot uses remaining time for EV energy
When planning starts inside a slot, the solver SHALL bound that slot's EV energy by the remaining duration (`slot_end − now`), not the full slot duration. All other flows and limits of that slot SHALL use the same remaining duration (see the `planner` capability, "In-progress slot uses one remaining-time basis").

#### Scenario: Replan 7 minutes into a slot
- **WHEN** a replan runs at 10:22 for the 10:15–10:30 slot and the goal needs 1.2 kWh by 10:30
- **THEN** the solver SHALL allow at most `max_power_kw × 8/60` kWh in that slot
- **AND** the reported kW for that slot SHALL be the planned energy divided by 8/60 h

#### Scenario: Surplus in a partial first slot
- **WHEN** a replan runs 7 minutes into a surplus-eligible slot
- **THEN** that slot's surplus EV energy terms SHALL use the 8/60 h remaining duration

#### Scenario: Replan at slot start
- **WHEN** a replan runs exactly at a slot boundary
- **THEN** the EV bounds SHALL be identical to before this change

#### Scenario: Remaining-duration bound applies to surplus energy
- **WHEN** planning starts inside a slot
- **THEN** the remaining-duration bound SHALL apply to both scheduled and surplus EV energy: the surplus reward, the surplus load in the energy balance, the excess-PV sink cap and the surplus energy counted toward the goal requirement SHALL all use the remaining duration

#### Scenario: Planned kW and other flows for the partial slot
- **WHEN** planning starts inside a slot
- **THEN** the planned EV kW for that slot SHALL be reported as energy divided by the remaining duration
- **AND** all other flows and limits in the slot SHALL use the same remaining duration, so every reported kW is energy divided by the remaining duration
