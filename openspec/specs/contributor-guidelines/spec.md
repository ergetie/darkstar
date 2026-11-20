## Purpose
Gives outside contributors and reporters the standard repository files and templates they expect, without publishing personal contact details.

## Requirements

### Requirement: Contributing guide
`CONTRIBUTING.md` SHALL describe the development setup with `uv` and `pnpm`, the `UV_NO_SYNC=1` prefix for ad-hoc `uv run` commands, running `./scripts/lint.sh`, conventional commit messages, the expectation that changes include tests, and how to contribute an inverter profile with a link to the profile creation guide.

#### Scenario: New contributor
- **WHEN** a contributor reads `CONTRIBUTING.md`
- **THEN** they can set up, run the checks, write a conforming commit and find the inverter profile guide

### Requirement: Code of conduct
`CODE_OF_CONDUCT.md` SHALL be Contributor Covenant 2.1, with enforcement reports directed to GitHub private reporting and the repository maintainers, and no email address.

#### Scenario: Reporting conduct issues
- **WHEN** a reader looks for how to report a violation
- **THEN** they are pointed to GitHub private reporting or the maintainers and no email address appears

### Requirement: Security policy
`SECURITY.md` SHALL direct reporters to GitHub private vulnerability reporting, state that the latest release is the supported version, and contain no email address.

#### Scenario: Reporting a vulnerability
- **WHEN** a reader opens `SECURITY.md`
- **THEN** it explains private reporting and which versions are supported

### Requirement: Issue and pull request templates
The repository SHALL provide a bug report template asking for Darkstar version, install type (Home Assistant add-on or Docker), inverter profile and a diagnostics bundle; an inverter profile request template; a `config.yml` for the issue chooser; and a pull request template.

#### Scenario: Filing a bug
- **WHEN** a user opens a new bug report
- **THEN** the form asks for version, install type, inverter profile and diagnostics bundle

#### Scenario: Opening a pull request
- **WHEN** a contributor opens a pull request
- **THEN** the description is pre-filled from the pull request template
