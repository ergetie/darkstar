## Purpose

Provides an automated offline check that learned battery parameters would have predicted real battery behaviour at least as well as the configured values, using archived planner runs and recorded data only.

## ADDED Requirements

### Requirement: Walk-forward replay compares config and learned efficiencies
For every archived planner run, the evaluator SHALL estimate the learned parameters using only data recorded before the run started, then roll the SoC forward from the recorded start SoC under both the configuration efficiencies used by that run and the learned effective efficiencies, and report mean absolute SoC error and bias at 6, 12 and 24 hours for each. Both arms SHALL use the same AC-side battery flows, derived per slot from the energy balance, never the DC-side counters.

#### Scenario: Learned closer to reality
- **WHEN** recorded flows were produced with efficiencies near the learned values and the config values are 4 points off
- **THEN** the report shows a smaller error for the learned values

#### Scenario: Consistent basis
- **GIVEN** a synthetic dataset generated from a known DC battery with known AC-side inverter losses
- **WHEN** the evaluator runs with a config pair equal to the truth and a learned pair 4 points off, and again with the pairs swapped
- **THEN** it ranks the arm closer to the truth better in both cases, and a roll-forward that applies the AC-side pair to DC counters would not give the same result

#### Scenario: Only fully eligible horizons
- **WHEN** a slot inside a run's horizon is not eligible (unreliable base load, unclean recording, null value)
- **THEN** the run is skipped for the horizons that contain it and the report states why

#### Scenario: No leakage
- **WHEN** a run starts on day 40
- **THEN** its learned values use only slots recorded before that start

### Requirement: The evaluator can fail a check
The tool SHALL exit non-zero when, over all evaluated runs, the learned values have a larger mean absolute SoC error at 24 hours than the config values by more than 0.25 percentage points, or when fewer than 10 runs were evaluable. A report SHALL state the runs used, those skipped and why.

#### Scenario: Learned worse
- **WHEN** learned values give 2.0 pp and config values 1.5 pp
- **THEN** the exit code is non-zero

#### Scenario: Too few runs
- **WHEN** 4 runs are evaluable
- **THEN** the exit code is non-zero and the report says so

### Requirement: Optional plan-sensitivity replay
With `--replan`, the evaluator SHALL re-solve each archived run through the planner pipeline under both parameter sets and report, per run, the number of slots whose battery action differs and the change in planned charge energy. This replay SHALL be informational and SHALL NOT affect the exit code.

#### Scenario: Replan report
- **WHEN** the tool runs with `--replan` on two archived runs
- **THEN** the report lists both runs with differing-slot counts

### Requirement: The evaluator is read-only
The tool SHALL read the archive directory and the learning database read-only, SHALL NOT write `config.yaml`, the database, `schedule.json` or the archive, and SHALL NOT use the network or Home Assistant.

#### Scenario: Files unchanged
- **WHEN** the tool runs
- **THEN** the archive directory, database and config have identical contents afterwards
