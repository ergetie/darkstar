# ev-per-charger-energy Specification

## Purpose
Persist recorded EV energy per charger so delivered energy and costs are tracked per charger rather than as a site aggregate.
## Requirements
### Requirement: Per-charger recorded EV energy is persisted
For each recorded slot, the system SHALL persist each enabled charger's measured energy, keyed by (`slot_start`, `charger_id`), in the same write as the slot observation. The aggregate `slot_observations.ev_charging_kwh` SHALL remain the sum over chargers.

#### Scenario: Two chargers recorded
- **WHEN** a slot records 1.2 kWh for `ev1` and 0.8 kWh for `ev2`
- **THEN** two per-charger rows SHALL be stored with those values
- **AND** the slot's `ev_charging_kwh` SHALL be 2.0

#### Scenario: Re-recording a slot is idempotent
- **WHEN** the same slot is recorded again with updated values
- **THEN** the per-charger rows SHALL be replaced, not duplicated

### Requirement: Delivered energy is per charger
The delivered-today value used by the planner and the persisted `delivered_kwh` SHALL be the sum of that charger's per-charger rows since local midnight. "Now" SHALL be the planner's effective time (honouring `now_override`). When no per-charger rows exist, delivered SHALL count as unknown, and SHALL NOT fall back to the unattributable aggregate.

#### Scenario: Multi-charger delivered
- **WHEN** today `ev1` has 5 kWh and `ev2` has 3 kWh recorded
- **THEN** `ev1`'s delivered SHALL be 5 and `ev2`'s SHALL be 3

#### Scenario: No per-charger data yet
- **WHEN** no per-charger rows exist for today for `ev1`
- **THEN** `ev1`'s delivered SHALL be unknown, and no delivered-today subtraction SHALL be applied
