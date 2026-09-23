## ADDED Requirements

### Requirement: Configurable solver time limit
The Kepler solver time limit SHALL be read from `kepler.solver_time_limit_s` (default 60, valid range 10–600) and applied to both CBC and GLPK. The value SHALL be editable in the settings UI with help text. The non-optimal timeout classification SHALL use the configured limit instead of a hardcoded value.

#### Scenario: Default limit
- **WHEN** `kepler.solver_time_limit_s` is absent from config
- **THEN** the solver SHALL run with a 60 s time limit

#### Scenario: Out-of-range value
- **WHEN** a user saves `solver_time_limit_s: 5`
- **THEN** validation SHALL reject it with the allowed range

### Requirement: Solver time-limit hits are detected and surfaced
The planner SHALL treat a solve as time-limited when its duration is ≥ the configured limit minus 0.5 s, even when the solver reports "Optimal". The planner SHALL then log a WARNING naming the limit and the duration, and SHALL set `time_limit_hit: true` in the result and in the persisted schedule metadata.

#### Scenario: CBC returns incumbent at limit
- **WHEN** the solver reports "Optimal" after 60.1 s with a 60 s limit
- **THEN** a WARNING SHALL be logged and the schedule metadata SHALL contain `time_limit_hit: true`
