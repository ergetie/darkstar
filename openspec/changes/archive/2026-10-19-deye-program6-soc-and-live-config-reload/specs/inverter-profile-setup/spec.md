## ADDED Requirements

### Requirement: Profiles may declare a setup notice
A profile MAY define `metadata.setup_notice` with `title` (string), `severity` (`info` or `warning`) and `items` (list of strings). Profile validation SHALL reject other types or severities. `list_profiles()` SHALL include `setup_notice` (or null). The UI SHALL show it in the onboarding profile step and in Settings > System when that profile is selected, following the design system.

#### Scenario: Deye selected
- **WHEN** the user selects the Deye profile
- **THEN** a notice says to set all six program times to 00:00 with Time of Use enabled, that Darkstar controls program 6 SoC, and that the master SoC helper automation is no longer needed

#### Scenario: Profile without notice
- **WHEN** a profile has no `setup_notice`
- **THEN** no notice is rendered

#### Scenario: Invalid notice
- **WHEN** `setup_notice.severity` is `critical`
- **THEN** profile validation reports an error

### Requirement: Deye program times are verified
For the Deye profile, health SHALL check the six program time entities. They SHALL be derived only from `soc_target` by replacing the program number with 1-6, `soc` with `time` and the domain with `time`. A mismatch SHALL be a health warning, never an error. Failure to verify SHALL NOT produce a health issue; only the dismissible setup-notice info is shown.

#### Scenario: All 00:00
- **GIVEN** `soc_target: number.inverter_program_6_soc` and `time.inverter_program_1_time` ... `_6_time` all `00:00:00`
- **THEN** no program-time issue is reported

#### Scenario: A time differs
- **WHEN** `time.inverter_program_3_time` is `05:00:00`
- **THEN** a warning names the entity and its value

#### Scenario: Cannot derive or entity missing
- **WHEN** `soc_target` is `input_number.master_soc_target`, or a derived entity does not exist or is unavailable
- **THEN** health reports no program-time issue
- **AND** the Deye setup notice in onboarding and Settings shows info "Couldn't verify program times" until the user dismisses it

#### Scenario: Dismissal persists
- **WHEN** the user dismisses the "Couldn't verify" info
- **THEN** it stays hidden after reload and restart
