## ADDED Requirements

### Requirement: Critical untested infrastructure modules have characterization tests

The highest-risk untested core infrastructure modules that bridge planner, executor, and Home Assistant SHALL have characterization tests that pin their current externally-observable behavior, so that later refactors are protected by a regression net.

#### Scenario: HA WebSocket client is characterized
- **WHEN** the test suite runs
- **THEN** `backend/ha_socket.py` has dedicated tests exercising its connection, message-handling, and reconnection behavior against a fake/mocked socket

#### Scenario: Planner/executor service wrappers are characterized
- **WHEN** the test suite runs
- **THEN** the planner→executor service wrappers (`backend/services/planner_service.py`, `backend/services/recorder_service.py`) have dedicated tests covering their orchestration behavior

### Requirement: Operational warnings use the structured logger

Library and service code SHALL emit operational warnings through the structured logger, not `print()`, so that warnings respect log levels and handlers and appear in log capture and alerting. A lint check SHALL enforce this.

#### Scenario: No print() in library/service code
- **WHEN** the lint check runs over `backend/`, `planner/`, `ml/`, and `executor/`
- **THEN** it flags any `print(...)` call as a violation
- **AND** `scripts/` and CLI entrypoints are exempt

#### Scenario: Existing print warnings are converted
- **WHEN** `planner/inputs/weather.py` fails to fetch a temperature forecast, or `ml/evaluate.py` finds no history available
- **THEN** the warning is emitted via the module logger (`logger.warning(...)`)
- **AND** no `print(...)` is used for that warning
