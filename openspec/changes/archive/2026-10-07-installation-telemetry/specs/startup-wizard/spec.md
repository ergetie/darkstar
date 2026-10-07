## ADDED Requirements

### Requirement: Installation statistics choice in final review
The final Review & readiness step SHALL include a clearly labeled installation-statistics toggle initialized from effective `installation_stats.enabled`, enabled when absent. Concise helper text SHALL disclose the daily random installation ID, version, release channel, installation type, CPU architecture, and inverter profile reporting, with custom profile names excluded. The final save SHALL persist this choice before marking onboarding complete. This control SHALL NOT add a wizard step, affect readiness results, trigger execution, force existing users through onboarding, or create an upgrade notice. A rerun SHALL preserve and display the saved choice.

#### Scenario: Fresh installation finishes with default reporting
- **WHEN** a new installation reaches Review & readiness and finishes without changing the statistics toggle
- **THEN** the toggle is enabled and reporting remains enabled
- **AND** existing shadow-mode and go-live completion behavior is preserved

#### Scenario: Disable reporting before finishing
- **WHEN** a user turns the final-review toggle off and successfully finishes
- **THEN** `installation_stats.enabled` is saved as false before onboarding is marked completed
- **AND** the sender re-evaluates the saved choice and dispatches no subsequent heartbeat

#### Scenario: Rerun or save failure
- **WHEN** a user reruns onboarding after disabling reporting
- **THEN** the toggle starts disabled and is not silently re-enabled
- **AND** a failed final save keeps onboarding incomplete and displays the existing save error
