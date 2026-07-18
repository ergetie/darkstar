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

### Requirement: Dependencies resolve identically in CI, local, and Docker

All direct Python dependencies (runtime and dev) SHALL be exactly pinned (`==`) in `requirements.txt`/`requirements-dev.txt`, so CI, local environments, and Docker builds resolve identical versions. Toolchain versions SHALL match across environments: the Python minor version, Node major version, and pnpm major version used in `.github/workflows/ci.yml` SHALL equal those installed by the Dockerfiles. Version holds/ceilings SHALL carry an in-file comment stating the reason and the condition for lifting them.

#### Scenario: No loose ranges remain
- **WHEN** `requirements.txt` and `requirements-dev.txt` are inspected after the upgrade pass
- **THEN** every direct dependency uses an exact `==` pin
- **AND** any intentional ceiling (e.g. a not-yet-migratable major) has a comment with reason and lift condition

#### Scenario: CI and Docker toolchains agree
- **WHEN** `.github/workflows/ci.yml` and the three Dockerfiles are compared
- **THEN** they specify the same Python minor, Node major, and pnpm major versions

#### Scenario: Upgrades are gated
- **WHEN** any dependency version is changed
- **THEN** the full local CI gate (`scripts/ci_local.sh`: lint, typecheck, full test suite) SHALL pass before the change is committed

### Requirement: Frontend lint runs the full react-hooks recommended rule set

The frontend ESLint configuration (`frontend/eslint.config.js`) SHALL enable the complete `eslint-plugin-react-hooks` recommended rule set without disabling any of its rules. In particular, `react-hooks/set-state-in-effect`, `react-hooks/static-components`, `react-hooks/purity`, and `react-hooks/immutability` SHALL be active at their recommended severity, and the frontend codebase SHALL lint clean under them.

#### Scenario: Lint gate catches hook-safety regressions

- **WHEN** `npx eslint .` (or the lint step of `scripts/ci_local.sh`) runs over the frontend
- **THEN** the four rules above are active and report zero findings on the codebase

#### Scenario: Rules are not silently disabled again

- **WHEN** the frontend ESLint config is inspected
- **THEN** it contains no `'off'` override for any `react-hooks/*` rule from the recommended set
