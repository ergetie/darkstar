## Purpose

Controls how many threads the Kepler CBC solve uses (automatic detection of available CPU cores with an optional `kepler.solver_threads` override), and the default solve time limit.

## Requirements

### Requirement: Automatic solver thread count
The Kepler CBC solve SHALL use multiple threads by default, equal to the number of CPU cores actually available to the process, with a minimum of 1.

#### Scenario: Auto with CPU affinity
- **WHEN** `kepler.solver_threads` is absent or 0 and the process is restricted to 4 cores
- **THEN** CBC is run with 4 threads

#### Scenario: Container CPU quota
- **WHEN** auto mode is active and a cgroup CPU quota allows fewer cores than the affinity set
- **THEN** the thread count is the quota rounded up, but at least 1

#### Scenario: Detection unavailable
- **WHEN** affinity and quota cannot be determined
- **THEN** the total CPU count is used, or 1 if that is unknown

### Requirement: Configurable thread override
The system SHALL accept an optional `kepler.solver_threads` setting; 0 or absent means auto, and integers 1-64 set the thread count explicitly.

#### Scenario: Explicit override
- **WHEN** `kepler.solver_threads` is 2
- **THEN** CBC is run with 2 threads regardless of available cores

#### Scenario: Invalid value at runtime
- **WHEN** the value is non-numeric, negative or above 64
- **THEN** a warning is logged and auto mode is used

#### Scenario: Invalid value via API
- **WHEN** a config save contains `kepler.solver_threads` outside 0-64 or non-integer
- **THEN** the save is rejected with a validation message naming the key

### Requirement: Thread count is logged
The system SHALL log the thread count used for each CBC solve.

#### Scenario: Solve logged
- **WHEN** a CBC solve starts
- **THEN** the log includes the thread count

### Requirement: Default solve time limit of 90 seconds
The default `kepler.solver_time_limit_s` SHALL be 90 seconds, with a valid range of 10-600 seconds. Explicit user values SHALL be honored unchanged.

#### Scenario: No value configured
- **WHEN** `kepler.solver_time_limit_s` is absent
- **THEN** the solve time limit is 90 seconds

#### Scenario: Existing user value
- **WHEN** a user config sets `kepler.solver_time_limit_s` to 60
- **THEN** 60 seconds is used

### Requirement: GLPK and time-limit detection unchanged
Solver selection order (GLPK first, CBC fallback) and `time_limit_hit` detection SHALL remain unchanged; only CBC receives the thread setting.

#### Scenario: CBC fallback
- **WHEN** GLPK is unavailable
- **THEN** CBC is used with the resolved thread count and time limit
