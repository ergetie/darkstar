## ADDED Requirements

### Requirement: Configured battery cycle cost is a hard floor on solver wear cost
The wear cost the solver uses (`wear_cost_sek_per_kwh`) SHALL never be lower than the configured battery cycle cost (`battery_economics.battery_cycle_cost_kwh`). This floor SHALL be enforced at the single solver-adapter resolution point where the wear cost is finalized, so it holds regardless of which source set the value (StrategyEngine override, root-level config, or default). The effective value SHALL be `max(battery_cycle_cost_kwh, resolved_wear_cost)`.

The configured cycle cost represents a fixed physical cost of using the battery; the StrategyEngine MAY raise the effective wear cost above the floor to demand more caution, but MUST NOT push it below the floor. The battery SHALL never be modelled as free to cycle.

#### Scenario: High-volatility override is clamped to the floor
- **GIVEN** `battery_economics.battery_cycle_cost_kwh = 0.2` and the StrategyEngine sets a wear-cost override of `0.0` (aggressive, high price spread)
- **WHEN** the adapter resolves the solver wear cost
- **THEN** the solver receives `0.2` (the configured floor), not `0.0`

#### Scenario: Conservative override above the floor is preserved
- **GIVEN** `battery_economics.battery_cycle_cost_kwh = 0.2` and the StrategyEngine sets a wear-cost override of `1.0` (conservative, flat market)
- **WHEN** the adapter resolves the solver wear cost
- **THEN** the solver receives `1.0` (override is above the floor, so it is kept)

#### Scenario: Floor enforced at a single resolution point
- **WHEN** the wear cost reaches the solver from any source
- **THEN** the `max(cycle_cost, …)` clamp has been applied exactly once at the adapter resolution point
- **AND** no code path can deliver a solver wear cost below the configured cycle cost
