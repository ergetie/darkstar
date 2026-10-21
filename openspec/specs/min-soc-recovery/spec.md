## Purpose

Defines how the planner recovers when the measured battery SoC is already below `battery.min_soc_percent`, so that small drifts are refilled at a cheap time instead of immediately at any price.

## Requirements

### Requirement: Recovery window for a small deficit
When the initial SoC is below `battery.min_soc_percent` by at most 5 percentage points, the solver SHALL use the initial SoC as the lower bound for every SoC state that lies less than 6 hours after the start of the first slot, and `min_soc_percent` for every later state. Both values are fixed, not user settings. The lower bound SHALL keep the existing `MIN_SOC_PENALTY` slack.

#### Scenario: Drift refilled at the cheaper slot
- **GIVEN** `capacity_kwh` 19.2, `min_soc_percent` 12, initial SoC 11%, no PV, import price 3.00 SEK/kWh for the first 3 hours and 0.50 SEK/kWh from hour 3 to hour 4
- **WHEN** the planner runs
- **THEN** no grid charging SHALL be planned in the first 3 hours
- **AND** no planned SoC state SHALL be below 11%
- **AND** the planned SoC SHALL be at least 12% at every state from 6 hours after the start onward

#### Scenario: Deadline enforced when no cheaper slot exists
- **GIVEN** `min_soc_percent` 12, initial SoC 11% and a flat import price
- **WHEN** the planner runs
- **THEN** the planned SoC SHALL be at least 12% at the state 6 hours after the start, without `soc_violation`

#### Scenario: Further decline not allowed
- **GIVEN** `min_soc_percent` 12 and initial SoC 11%
- **WHEN** the planner runs
- **THEN** no planned SoC state inside the window SHALL be below 11% unless the `MIN_SOC_PENALTY` slack is used

#### Scenario: Horizon shorter than the window
- **GIVEN** initial SoC 11%, `min_soc_percent` 12 and a horizon that ends 4 hours after the start
- **WHEN** the planner runs
- **THEN** the terminal SoC state SHALL be held to 12%

#### Scenario: At or above the minimum is unchanged
- **WHEN** the initial SoC is at or above `min_soc_percent`
- **THEN** every SoC state SHALL use `min_soc_percent` as its lower bound, exactly as before

### Requirement: Deep deficit refills immediately
When the initial SoC is more than 5 percentage points below `battery.min_soc_percent`, the solver SHALL use `min_soc_percent` as the lower bound for every SoC state after the initial one, so the deficit is refilled as soon as charge power allows regardless of price.

#### Scenario: Six points below the minimum
- **GIVEN** `min_soc_percent` 12, initial SoC 6%, import price 3.00 SEK/kWh now and 0.50 SEK/kWh in 3 hours
- **WHEN** the planner runs
- **THEN** the first slot SHALL plan grid charging toward 12%

#### Scenario: Exactly five points below uses the window
- **GIVEN** `min_soc_percent` 12 and initial SoC 7%
- **WHEN** the planner runs
- **THEN** the recovery window SHALL apply

### Requirement: Export floor uses the recovery lower bound
Where the export-floor constraint falls back to the minimum SoC for slots that do not export, it SHALL use the same per-state lower bound as the minimum-SoC constraint.

#### Scenario: No forced refill through the export floor
- **GIVEN** `export_floor_soc_percent` 20, `min_soc_percent` 12 and initial SoC 11%
- **WHEN** the planner runs
- **THEN** non-export slots inside the window SHALL NOT incur `export_floor_violation` for SoC between 11% and 12%

### Requirement: Benchmark solves are unaffected
Battery benchmark solves SHALL keep their own lower bound (the minimum of `min_soc`, the recorded start SoC and the recorded end SoC) and SHALL NOT apply the recovery window.

#### Scenario: Benchmark below minimum
- **GIVEN** a benchmark day that starts at 10% with `min_soc_percent` 12
- **WHEN** the benchmark solve runs
- **THEN** its lower bound SHALL be 10% for every state, as before

### Requirement: Charge targets follow the planned recovery
A charge block's `soc_target` SHALL be the projected SoC at the block end, clamped to `max_soc_percent` but not raised to `min_soc_percent`. Hold slots SHALL keep their entry SoC as target and discharge slots SHALL keep `min_soc_percent`, so a hold below the minimum during recovery does not trigger grid charging.

#### Scenario: Partial recovery charge
- **GIVEN** `min_soc_percent` 12 and a charge block whose projected end SoC is 11.4%
- **WHEN** SoC targets are derived
- **THEN** the block's `soc_target` SHALL be 11

#### Scenario: Normal charge block unchanged
- **GIVEN** a charge block whose projected end SoC is 80%
- **WHEN** SoC targets are derived
- **THEN** the block's `soc_target` SHALL be 80

#### Scenario: Hold during recovery
- **GIVEN** `min_soc_percent` 12 and a hold slot whose entry SoC is 11%
- **WHEN** SoC targets are derived
- **THEN** the slot's `soc_target` SHALL be 11
