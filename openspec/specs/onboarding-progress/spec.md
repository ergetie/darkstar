# onboarding-progress Specification

## Purpose
Persist validated onboarding progress so setup can resume across browser sessions.

## Requirements

### Requirement: Persisted onboarding state
The system SHALL persist onboarding state in `data/onboarding_state.json` with `version`, `status` (`not_started|in_progress|dismissed|completed`), `current_step`, `completed_steps` and `updated_at`, written atomically. It SHALL be exposed via `GET /api/setup/onboarding` and `PUT /api/setup/onboarding`.

#### Scenario: No state file
- **WHEN** the state file does not exist
- **THEN** `GET` SHALL return `status: "not_started"`

#### Scenario: Progress saved
- **WHEN** the client puts `{status: "in_progress", current_step: "pricing", completed_steps: ["connect","system"]}`
- **THEN** a subsequent `GET` SHALL return the same values from any browser

#### Scenario: Invalid status rejected
- **WHEN** the client puts an unknown status
- **THEN** the endpoint SHALL return HTTP 422 and SHALL NOT modify the file

#### Scenario: Corrupt file
- **WHEN** the state file is not valid JSON
- **THEN** `GET` SHALL return `status: "not_started"` and log a warning
