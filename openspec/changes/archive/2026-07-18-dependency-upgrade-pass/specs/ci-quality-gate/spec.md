## ADDED Requirements

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
