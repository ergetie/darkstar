## ADDED Requirements

### Requirement: Benchmark uses the effective battery efficiencies
The benchmark's hindsight solve and its capacity fit SHALL use the same effective charge and discharge efficiencies as the planner (learned, locked or config fallback).

#### Scenario: Learned efficiencies active
- **WHEN** learned efficiencies are valid at benchmark time
- **THEN** the hindsight Kepler configuration and the capacity fit use them

#### Scenario: Fallback
- **WHEN** no valid learned value exists
- **THEN** the configured efficiencies are used, as before
