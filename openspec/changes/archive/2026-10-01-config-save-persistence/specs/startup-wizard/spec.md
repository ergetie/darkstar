## ADDED Requirements

### Requirement: Missing-profile state reflects the saved config
The UI's missing-inverter-profile state (wizard trigger and "inverter profile not set" banner) SHALL be re-evaluated from freshly fetched config after the wizard completes and after any successful settings save, not only on initial page load.

#### Scenario: Banner clears after wizard completes
- **WHEN** a fresh install completes the wizard with profile `deye`
- **THEN** the "inverter profile not set" banner SHALL NOT be shown
- **AND** no page reload SHALL be required

#### Scenario: Banner clears after profile set in Settings
- **WHEN** the banner is shown and the user saves a non-null inverter profile in Settings
- **THEN** the banner SHALL disappear after the save succeeds
