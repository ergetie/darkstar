## ADDED Requirements

### Requirement: Installation statistics controls in System settings
Settings → System SHALL include a normal-mode searchable Installation statistics section with an enabled toggle and an editable receiver endpoint. Fields SHALL use the existing settings form, validation, dirty-change comparison, save/error flow, and design-system controls. The section SHALL explain the daily minimal payload and user control without adding a notice elsewhere. Successful changes SHALL notify the reporting service; a disabled value SHALL persist through reloads and upgrades. The endpoint SHALL remain editable when reporting is disabled.

#### Scenario: Disable through Settings
- **WHEN** a user turns off statistics reporting and saves
- **THEN** the enabled state is persisted as false and the sender re-evaluates it
- **AND** reloading Settings displays the disabled toggle

#### Scenario: Redirect to another receiver
- **WHEN** a user saves another valid absolute HTTPS endpoint
- **THEN** the next due heartbeat uses that endpoint
- **AND** normal save/unsaved-change behavior includes both statistics fields

#### Scenario: Invalid endpoint and discoverability
- **WHEN** a user tries to save a relative, HTTP, or credential-bearing endpoint
- **THEN** save is rejected with a clear field validation message
- **AND** both reporting controls remain discoverable without enabling advanced mode

#### Scenario: Endpoint edit while disabled
- **WHEN** reporting is disabled and a user saves a new valid endpoint
- **THEN** the endpoint is persisted without enabling reporting or sending a test ping
