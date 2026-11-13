# Spec Delta

## Purpose
Water heater phase wiring is configured once per device and is used by both the planner's per-phase fuse limit and the executor load balancer.

## ADDED Requirements

### Requirement: Water heater phases are a per-device setting
Each water heater SHALL accept `water_heaters[].phases`, a non-empty list of distinct integers in 1-3. When missing or invalid it SHALL default to `[1, 2, 3]` (power spread evenly over three phases). Config validation SHALL reject values outside 1-3, empty lists and duplicates.

#### Scenario: Default
- **WHEN** a water heater has no `phases`
- **THEN** it is treated as `[1, 2, 3]` and is not phase-limited

#### Scenario: Invalid value
- **WHEN** `phases` is `[4]` or `[]`
- **THEN** validation reports an error for that heater

### Requirement: Load balancer reads water heater phases from the device
For `device_type: water_heater` shed loads the balancer SHALL use `water_heaters[<device_id>].phases`. `loads[].phases` SHALL be ignored for them. `custom_entity` loads SHALL keep using `loads[].phases`; EV chargers keep `ev_chargers[].phases`.

#### Scenario: Device phase wins
- **WHEN** a water heater has `phases: [3]` and its `loads[]` entry has no `phases`
- **THEN** the balancer treats the heater as wired to L3

#### Scenario: Custom load unchanged
- **WHEN** a `custom_entity` load has `phases: [2]`
- **THEN** the balancer uses `[2]`

### Requirement: Planner per-phase limit includes phase-limited water heaters
The planner's per-phase import limit (`max_phase_import_kw`) SHALL include the power of each active water heater with fewer than 3 phases, spread as power / len(phases) on each of its own phase lines, together with phase-limited EV chargers. Base house load SHALL remain net import / 3. The constraint SHALL be active when any phase-limited EV charger or any phase-limited water heater exists, and SHALL NOT be active (no rows) when none exist.

#### Scenario: One-phase heater and EV on the same phase
- **WHEN** a 3 kW water heater on `[3]` and a 1-phase EV charger on `[3]` compete in the same slot and together would exceed the per-phase limit
- **THEN** the plan schedules them so line L3 stays at or below `max_phase_import_kw` in every slot (by moving or reducing one of them)

#### Scenario: Three-phase heater alone
- **WHEN** the only water heater has `phases: [1, 2, 3]` and no EV charger is phase-limited
- **THEN** no per-phase rows are added

### Requirement: Phase limit never makes the plan infeasible
The planner SHALL remain feasible for any water heater configuration. The daily minimum (`min_kwh_per_day`) stays a penalised soft target, and a heater slot forced on by `force_on_slots` (running block that cannot be interrupted) SHALL relax the phase row through a penalised slack instead of failing the solve.

#### Scenario: Forced-on heater over the limit
- **WHEN** a forced-on slot on one phase plus other load exceeds the limit
- **THEN** the solver returns a plan; the overshoot is carried by slack and logged, not an infeasible model
