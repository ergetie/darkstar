# Spec Delta: planner

## MODIFIED Requirements

### Requirement: Soft max-SoC bound with penalty
The Kepler MILP SHALL enforce `battery.max_soc_percent` as a soft constraint. The solver SHALL introduce a per-slot `soc_overshoot[t] >= 0` slack variable and replace the previous hard upper bound `soc[t] <= max_soc_kwh` with `soc[t] <= max_soc_kwh + soc_overshoot[t]`. The objective SHALL include a penalty term `MAX_SOC_PENALTY * sum(soc_overshoot[t])` where `MAX_SOC_PENALTY = 1000.0` (mirroring the existing `MIN_SOC_PENALTY`).

#### Scenario: Initial SoC above max produces a feasible plan
- **GIVEN** `battery.max_soc_percent = 95` and `capacity_kwh = 19.2` (max_soc_kwh = 18.24)
- **AND** measured initial SoC is 18.989 kWh (98.9%)
- **WHEN** the planner runs
- **THEN** the solver returns status `Optimal`
- **AND** the resulting plan's first slot begins with a discharge action (battery_charge_kw < 0) or an export action sufficient to reduce SoC toward the ceiling
- **AND** the `soc_overshoot` penalty is reflected in the total cost

#### Scenario: Initial SoC below max is unaffected
- **GIVEN** `battery.max_soc_percent = 95` and measured SoC is 10.0 kWh (52%)
- **WHEN** the planner runs
- **THEN** the solver returns status `Optimal`
- **AND** `soc_overshoot[t]` is zero for all slots

#### Scenario: Lower bound behavior unchanged
- **GIVEN** measured initial SoC is below `min_soc_kwh`
- **WHEN** the planner runs
- **THEN** the `soc_violation` slack and `MIN_SOC_PENALTY` SHALL apply against the per-state lower bound defined by the `min-soc-recovery` capability
- **AND** the max-SoC bound SHALL be unaffected

#### Scenario: Export floor config passed through adapter
- **GIVEN** `export_floor_soc_percent = 20` is configured in the planner config
- **WHEN** the adapter builds `KeplerConfig`
- **THEN** `KeplerConfig.export_floor_soc_percent` SHALL be 20.0
- **AND** the solver SHALL enforce the export-floor constraint

#### Scenario: Initial SoC clipped to physical range
- **WHEN** `initial_soc` is clipped to the physical range
- **THEN** the clipping SHALL use `[0, capacity_kwh]` only
- **AND** it SHALL NOT clip to `[min_soc_kwh, max_soc_kwh]`

#### Scenario: KeplerConfig export floor field
- **WHEN** `KeplerConfig` has `export_floor_soc_percent` set and `enable_export` is True
- **THEN** `KeplerConfig` SHALL include an `export_floor_soc_percent: float | None` field
- **AND** the solver SHALL add a per-slot binary `is_exporting[t]` and enforce that grid export is only allowed when `soc[t] >= export_floor_kwh`, using a soft constraint with `EXPORT_FLOOR_PENALTY = 1000.0`
