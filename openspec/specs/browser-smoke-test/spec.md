## Purpose
Provides an automated browser-level check that the built UI boots against the real backend even when Home Assistant is unreachable, so broken bundles or startup regressions are caught before release.

## Requirements

### Requirement: Smoke test against the real backend
A Playwright smoke test SHALL start the real backend with Home Assistant unavailable, using a throwaway configuration and data directory inside the project that is ignored by git, and serving the built frontend. It SHALL load the dashboard and the settings page and assert that each renders content without uncaught page errors or console errors.

#### Scenario: Dashboard loads
- **WHEN** the smoke test opens the dashboard
- **THEN** the application shell renders and no page or console error is recorded

#### Scenario: Settings loads
- **WHEN** the smoke test opens the settings page
- **THEN** the settings view renders and no page or console error is recorded

#### Scenario: Repository data untouched
- **WHEN** the smoke test runs
- **THEN** it reads and writes only its own temporary configuration and data, never the developer's `config.yaml`, `secrets.yaml` or databases

### Requirement: Separate from unit tests
The browser test SHALL run through its own `test:e2e` script and SHALL NOT be collected by the default `pnpm test` (vitest) run.

#### Scenario: Default test run
- **WHEN** `pnpm test` runs
- **THEN** no Playwright test is executed

### Requirement: Continuous integration job
CI SHALL run the smoke test in a dedicated job that installs Chromium and fails the workflow when the test fails.

#### Scenario: Pull request
- **WHEN** a pull request is opened against `main`
- **THEN** the smoke job builds the frontend, installs Chromium and runs `pnpm test:e2e`
