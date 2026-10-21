## ADDED Requirements

### Requirement: In-progress slot uses one remaining-time basis
When planning starts inside a slot, the planner SHALL use the remaining duration `slot_end - now` for slot 0 in every flow, limit and cost: energy balance, surplus sink, battery limits, import/export limits, per-phase fuse row and EV supply bound. Slot-0 forecast energy SHALL be scaled to it, reported kW SHALL be energy divided by it, and the `now_override` path SHALL floor the slot start like the normal path.


#### Scenario: Grid limit holds in a partial slot
- **WHEN** planning starts with 4 minutes left in a slot and the import limit is 11 kW
- **THEN** slot-0 planned grid power SHALL be at most 11 kW

#### Scenario: Battery energy bounded by remaining time
- **WHEN** planning starts with 4 minutes left in a slot
- **THEN** slot-0 battery charge energy SHALL be at most `max_charge_kw x 4/60` kWh and the SoC trajectory SHALL reflect only that energy

#### Scenario: Slot boundary unchanged
- **WHEN** planning starts exactly on a slot boundary
- **THEN** the plan SHALL be identical to before this change

#### Scenario: now_override rounding
- **WHEN** `now_override` is inside a slot
- **THEN** the slot index SHALL equal the one chosen without the override

### Requirement: Fuse overloads are handled by the balancer, not by replans
The planner SHALL NOT be asked to replan because the runtime balancer is throttling. Overloads the plan cannot foresee SHALL be handled by the balancer giving way. Broader per-phase planning stays the backlog item "[Planner] Per-Phase Load Awareness".

#### Scenario: Sustained throttling
- **WHEN** the balancer has held an entry below its planned value for longer than one planner interval
- **THEN** no replan SHALL be requested and the balancer SHALL keep giving way
