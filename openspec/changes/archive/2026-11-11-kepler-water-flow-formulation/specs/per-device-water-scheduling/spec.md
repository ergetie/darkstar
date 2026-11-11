## ADDED Requirements

### Requirement: Water scheduling rules are modelled as an exact flow formulation
The solver SHALL model start, spacing, gap and block-overshoot rules per heater as a state-expanded arc-flow graph with unit flow per slot, where `water_heat[d][t]` is binary and equals the flow into on-states. The penalty paid by any heat pattern under this formulation SHALL equal the penalty defined by the gap, start, overshoot and symmetry rules. Other water rules SHALL continue to act on `water_heat[d][t]`.

#### Scenario: Fixed heat pattern pays the same penalty
- **GIVEN** a fixed heat pattern for a heater
- **WHEN** the penalty is evaluated in the flow formulation and in the previous start/spacing/discomfort/overshoot formulation
- **THEN** both SHALL be equal for spacing >= block cap, spacing < cap, spacing 0, gap rule on and off, bulk mode, a shortened first slot, `heated_today > 0`, force_on slots and boost

#### Scenario: Bulk mode reduces to start penalty only
- **GIVEN** `enable_top_ups: false` (spacing 0, gap rule off, no block penalty)
- **WHEN** the solver builds the water model
- **THEN** the graph SHALL only account for block starts and the plan SHALL equal the previous model's plan

#### Scenario: Initial state unchanged
- **WHEN** the horizon starts
- **THEN** the gap counter SHALL start at 0, spacing SHALL be truncated at slot 0, and `heated_today` SHALL NOT feed gap or spacing

#### Scenario: Time-limit detection and result extraction unchanged
- **WHEN** the solver finishes with the flow formulation
- **THEN** per-heater results and `time_limit_hit` SHALL be extracted as before

## MODIFIED Requirements

### Requirement: Per-device block duration constraint
The solver SHALL penalize per-device heating blocks longer than the maximum block duration, determined by the global `max_block_hours` setting, at `water_block_penalty_sek` per slot beyond the cap. When the heater's spacing is at least the block cap in slots, the overshoot SHALL be priced by an over-cap state in the heater's flow graph. When spacing is below the cap (or zero), the solver SHALL instead use sliding-window rows `sum(water_heat[d][t:t+window]) <= max_block_slots + overshoot[d]` for that heater.

#### Scenario: Two heaters with different block patterns
- **WHEN** heater A is scheduled for a 2-hour block and heater B needs a 1.5-hour block
- **THEN** the solver SHALL allow each heater's blocks up to the max block duration independently

#### Scenario: Block longer than the cap
- **WHEN** a heater's block exceeds the cap by n slots and spacing >= cap
- **THEN** the objective SHALL include `n * water_block_penalty_sek` for that block

### Requirement: Per-device spacing constraint
The solver SHALL enforce a per-device minimum spacing between block starts: an off-to-on transition is allowed only after at least `spacing_slots = max(1, int(min_spacing_hours / avg_slot_hours))` off slots, or when the heater has not heated since the plan start. Spacing 0 disables the rule.

#### Scenario: Two heaters with different spacing requirements
- **WHEN** heater A has `water_min_spacing_hours: 4` and heater B has `water_min_spacing_hours: 6`
- **THEN** heater A's block starts SHALL be at least 4 hours apart
- **AND** heater B's block starts SHALL be at least 6 hours apart

#### Scenario: Heaters can start blocks at the same time
- **WHEN** heater A and heater B both have cheap slots available at 03:00
- **THEN** the solver MAY schedule both heaters to start heating at 03:00
- **AND** this does NOT violate either heater's spacing constraint (spacing is per-device, not cross-device)

### Requirement: Per-device block start penalty
The solver objective SHALL include a per-device block start penalty of `water_block_start_penalty_sek` for every block start of every heater, carried by the off-to-on arcs of the heater's flow graph.

#### Scenario: Penalty discourages frequent starts per heater
- **WHEN** `block_start_penalty_sek: 3.0` and two heaters are configured
- **THEN** each block start for either heater incurs a 3.0 SEK penalty in the objective
- **AND** the solver prefers consolidated heating blocks for each heater

### Requirement: Per-device gap-comfort penalty with deadband
The Kepler solver SHALL bound the time between water-heating blocks per device using a soft, linear discomfort penalty with a deadband at the configured maximum gap. For every off slot, the cost SHALL be `water_gap_penalty_sek * max(0, hours since last heat including that slot - max_hours_between_heating)`, i.e. cumulative over a long off run. The cost SHALL be carried by the off-state arcs of the heater's flow graph, using each slot's actual duration.

#### Scenario: Gaps within the ceiling are free
- **GIVEN** a heater with `max_hours_between_heating = 8` and a schedule where the longest gap between heating is 6 hours
- **WHEN** the solver optimizes
- **THEN** no gap penalty is incurred and the gap penalty contributes 0 to the objective

#### Scenario: Gaps beyond the ceiling are penalized and broken up
- **GIVEN** a heater with `max_hours_between_heating = 8`, `water_gap_penalty_sek > 0`, prices cheap overnight and expensive by day
- **WHEN** the solver would otherwise bunch all heating overnight and leave a >8 h daytime gap
- **THEN** the solver SHALL insert a top-up heating block so no gap exceeds ~8 hours, unless the price saving outweighs the accrued gap penalty

#### Scenario: Gap penalty disabled in bulk mode and vacation
- **GIVEN** `enable_top_ups: false` (bulk mode) or vacation mode active, which disable gap comfort globally
- **WHEN** the solver optimizes
- **THEN** no gap cost SHALL be added

#### Scenario: Counter starts at zero at the horizon start
- **GIVEN** any planning horizon
- **WHEN** the solver builds the gap model
- **THEN** the gap counter SHALL start from 0 (plus the first slot's duration, less any heating in that slot)

#### Scenario: Different heater gaps are honored
- **WHEN** heater A has maximum gap 28 hours and heater B has maximum gap 8 hours
- **THEN** each SHALL use its own deadband rather than a shared default of 8 hours
- **AND** their gap penalties SHALL activate independently

#### Scenario: Gap penalty recurrence and objective term
- **WHEN** the water-heating gap penalty is active for heater `d`
- **THEN** the hours since last heat SHALL accumulate by each slot's duration and reset on every heated slot
- **AND** the objective SHALL include, per off slot, `water_gap_penalty_sek * max(0, accumulated hours - heater.max_hours_between_heating)`
- **AND** no sliding-window gap constraints SHALL be used

#### Scenario: Gap penalty activation conditions
- **WHEN** a heater's `max_hours_between_heating` is not above 0, top-ups are disabled, vacation mode is active, or `water_gap_penalty_sek` is not above 0
- **THEN** no gap cost SHALL be added
- **AND** the penalty SHALL be active for a heater only when its `max_hours_between_heating > 0`, top-ups are enabled, vacation mode is inactive, AND `water_gap_penalty_sek > 0`
