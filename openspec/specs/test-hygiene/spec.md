# Test Hygiene

## Purpose
This specification defines the standards for maintainable, warning-free, and thread-safe testing in the Darkstar environment. It aims to eliminate technical debt and ensure that the test suite provides high-signal feedback.

## Requirements

### Requirement: Warning-Free Logging
The system SHALL use the non-deprecated `pythonjsonlogger.json` structure for JSON logging.

#### Scenario: Logger initialization
- **WHEN** `backend/core/logging.py` is initialized
- **THEN** it imports from `pythonjsonlogger.json` and no `DeprecationWarning` is issued.

### Requirement: Modern Pydantic Configurations
The system SHALL use the Pydantic V2 `model_config` syntax for model configuration.

#### Scenario: Pydantic model validation
- **WHEN** `backend/api/routers/forecast.py` is imported or `BriefingRequest` is instantiated
- **THEN** no `PydanticDeprecatedSince20` warning is issued.

### Requirement: Timezone-Aware UTC Usage
The system SHALL use `datetime.now(UTC)` instead of `datetime.utcnow()` for UTC timestamps.

#### Scenario: UTC timestamp generation
- **WHEN** tests generate UTC timestamps (e.g., in `tests/ml/test_ml_history.py`)
- **THEN** they use `datetime.now(UTC)` and no `DeprecationWarning` is issued.

### Requirement: Guaranteed Thread Safety in Tests
The system SHALL ensure that no `AsyncEngine` instance is created in session-scoped fixtures. Per-test fixtures that create engines SHALL explicitly await `engine.dispose()` before the test event loop is closed.

#### Scenario: Database test cleanup
- **WHEN** a per-test fixture creates a database engine
- **THEN** it explicitly awaits `engine.dispose()` to ensure background threads are terminated before the test event loop closes.

### Requirement: Test Isolation from Production Config
The system SHALL NOT read from or write to `config.yaml` during any test session. Test config SHALL be injected via a monkey-patch of `inputs.load_yaml` in the session fixture.

#### Scenario: Test session does not corrupt config.yaml
- **WHEN** `uv run python -m pytest` is executed (or aborted mid-run)
- **THEN** `config.yaml` on disk is identical before and after the run.

#### Scenario: All callers of `inputs.load_yaml("config.yaml")` receive test config
- **WHEN** any module calls `inputs.load_yaml("config.yaml")` during a test session
- **THEN** it receives the in-memory test config dict without reading the filesystem.

### Requirement: aiosqlite Engine Cleanup

The system SHALL ensure that any test creating an aiosqlite-backed component (such as `LearningStore`) calls the appropriate cleanup method before the test event loop closes.

#### Scenario: LearningStore cleanup in async test
- **WHEN** a test creates a `LearningStore` instance with `:memory:` or file-based SQLite
- **THEN** the test calls `await store.close()` in a `finally` block to ensure the background connection thread terminates before the event loop closes.

#### Scenario: pytest-asyncio fixture uses yield for teardown
- **WHEN** a `@pytest_asyncio.fixture` creates a `LearningStore` or `LearningEngine`
- **THEN** the fixture uses `yield` (not `return`) so that `await store.close()` runs in the teardown phase before the event loop closes.

#### Scenario: Event loop teardown without warnings
- **WHEN** pytest-asyncio closes the event loop after a test that used aiosqlite
- **THEN** no `RuntimeError: Event loop is closed` or `PytestUnhandledThreadExceptionWarning` is raised.

### Requirement: Live Service Isolation in API Tests

API tests SHALL NOT start real background services (executor engine, HA WebSocket client) that connect to live external systems.

#### Scenario: No real executor during API tests
- **WHEN** an API test creates a `TestClient` that triggers the FastAPI lifespan
- **THEN** `get_executor_instance()` returns `None` so no `ExecutorEngine`, `HAClient`, or `aiohttp.ClientSession` is created, and no aiohttp shutdown noise appears after the test run.

#### Scenario: No real HA WebSocket during API tests
- **WHEN** an API test creates a `TestClient` that triggers the FastAPI lifespan
- **THEN** `start_ha_socket_client()` is a no-op so no daemon thread connects to the live HA instance, preventing `RuntimeWarning: coroutine was never awaited` from cross-thread event-loop interactions.

### Requirement: Meaningful Async Declarations

The system SHALL NOT declare functions as `async` unless they perform async operations (use `await`).

#### Scenario: Synchronous function declaration
- **WHEN** a function performs only synchronous operations (file I/O, dict manipulation, etc.)
- **THEN** it is declared as a regular `def` function, not `async def`.

#### Scenario: Test markers match function type
- **WHEN** a test only calls synchronous functions
- **THEN** it does not use `@pytest.mark.asyncio`.

#### Scenario: No unawaited coroutine warnings
- **WHEN** pytest runs the full test suite
- **THEN** no `RuntimeWarning: coroutine was never awaited` is raised.

### Requirement: Clean Test Suite Baseline
The full test suite SHALL execute with zero `DeprecationWarning` and zero `PytestUnhandledThreadExceptionWarning` messages. The lint script SHALL exit non-zero if any check (including frontend linting) fails.

#### Scenario: Full suite execution
- **WHEN** `uv run python -m pytest` is executed
- **THEN** the output contains the current passing count and zero warnings.

#### Scenario: lint.sh propagates frontend lint failures
- **WHEN** `./scripts/lint.sh` is executed and `pnpm lint` exits non-zero
- **THEN** `lint.sh` exits non-zero and does NOT print "✅ All checks passed!".

### Requirement: Consistent pytest invocation

The test suite SHALL be runnable via both `uv run pytest` and `uv run python -m pytest` with identical behavior.

#### Scenario: Bare pytest invocation
- **WHEN** a developer runs `uv run pytest` from the project root
- **THEN** all tests pass without `ModuleNotFoundError`
- **AND** the behavior is identical to `uv run python -m pytest`

### Requirement: CI pipeline reflects current source layout

The CI pipeline SHALL only reference source paths that exist in the current project structure.

#### Scenario: Ruff lint step
- **WHEN** the CI pipeline runs the ruff lint step
- **THEN** it checks all Python source directories that exist (e.g., `backend/`)
- **AND** it does not reference deleted files (e.g., the former root-level `inputs.py`)

### Requirement: Critical dependencies pinned with version bounds

Database-layer dependencies (SQLAlchemy, Alembic) SHALL have explicit version bounds to prevent uncontrolled major-version upgrades.

#### Scenario: Fresh install
- **WHEN** running `pip install -r requirements.txt` on a clean environment
- **THEN** SQLAlchemy installs within the 2.x range
- **AND** Alembic installs within the 1.x range

### Requirement: Critical untested infrastructure modules have characterization tests

The highest-risk untested core infrastructure modules that bridge planner, executor, and Home Assistant SHALL have characterization tests that pin their current externally-observable behavior, so that later refactors are protected by a regression net.

#### Scenario: HA WebSocket client is characterized
- **WHEN** the test suite runs
- **THEN** `backend/ha_socket.py` has dedicated tests exercising its connection, message-handling, and reconnection behavior against a fake/mocked socket

#### Scenario: Planner/executor service wrappers are characterized
- **WHEN** the test suite runs
- **THEN** the planner->executor service wrappers (`backend/services/planner_service.py`, `backend/services/recorder_service.py`) have dedicated tests covering their orchestration behavior

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

### Requirement: Frontend data-transform logic is unit-tested as pure functions

Frontend logic that transforms data for display — chart series building, power-flow partitioning and node enablement, schedule/slot day math, price breakdown, cost aggregation, progress/status derivation, and value formatters with branching logic — SHALL be importable as pure functions (module-level, exported) and SHALL have unit tests. These tests SHALL include configuration-variation cases for hardware setups the maintainer does not run: absent battery, absent EV charger, zero and multiple chargers, absent water heater, and empty/missing optional data fields. Tests for time-dependent logic SHALL use injected/fixed time (fake timers), never the machine wall clock. New render/component tests and E2E tests are explicitly NOT required by this requirement.

#### Scenario: Chart data builder handles a battery-less config
- **WHEN** the 48h chart data builder receives schedule slots with no battery fields (no `charge_kw`/`discharge_kw`)
- **THEN** it SHALL produce null/empty charge and discharge series without `NaN` values or exceptions

#### Scenario: Power-flow logic handles absent EV data
- **WHEN** power-flow partitioning receives data with no `ev` entry, or node enablement receives a config with `has_battery: false`
- **THEN** the EV/battery nodes SHALL be absent from the computed output without error

#### Scenario: Aggregations survive empty inputs
- **WHEN** cost-drift, normalization, or summary logic receives an empty series/slot list
- **THEN** it SHALL return its documented empty-state value (zero drift, flat normalization, null summary) rather than `NaN` or a thrown error

#### Scenario: Time-dependent tests are wall-clock independent
- **WHEN** unit tests exercise "today"/"tomorrow"/date-range logic
- **THEN** they SHALL set a fixed system time (including DST-boundary and near-midnight instants) and restore real timers afterward

#### Scenario: Surprising current behavior is pinned
- **WHEN** logic has a deliberate but non-obvious fallback (e.g. null system config excluding the EV node from the power flow)
- **THEN** a test SHALL assert the current behavior explicitly, so any future change to it is a conscious, reviewed decision
