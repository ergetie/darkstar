# CI Quality Gate

## Purpose
This specification defines CI merge gates that keep the Python test suite and strict type checks effective for every pull request and default-branch update.

## Requirements

### Requirement: CI runs the full Python test suite

The CI pipeline SHALL execute the complete Python test suite on every pull request and on the default branch, not a single-file subset, and SHALL block the merge if any test fails.

#### Scenario: Full suite runs in CI
- **WHEN** a pull request triggers `.github/workflows/ci.yml`
- **THEN** the test step runs `uv run python -m pytest` over the whole `tests/` tree (planner, executor, ml, backend, api)
- **AND** it does not restrict execution to `tests/api/test_api_routes.py`

#### Scenario: Non-API regression blocks merge
- **WHEN** a change breaks a planner, executor, or ML test
- **THEN** the CI test job fails
- **AND** the pull request is not mergeable while the failure stands

### Requirement: CI enforces pyright strict as a merge gate

The CI pipeline SHALL run pyright in the strict mode configured in `pyproject.toml` as a required check, so type regressions block the merge rather than being caught only by local pre-commit.

#### Scenario: Type error blocks merge
- **WHEN** a pull request introduces a pyright strict error
- **THEN** the dedicated pyright CI job fails
- **AND** the pull request is not mergeable while the error stands

#### Scenario: Pyright job uses the project configuration
- **WHEN** the pyright CI job runs
- **THEN** it uses the strict settings declared in `pyproject.toml`
- **AND** it does not relax them to a weaker mode
