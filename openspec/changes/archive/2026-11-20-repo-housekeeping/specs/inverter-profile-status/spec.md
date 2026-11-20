# Spec Delta

## Purpose
Lets users tell hardware-verified inverter profiles from community-contributed ones. The backend decides the status and the UI only displays it.

## ADDED Requirements

### Requirement: Profile status metadata
An inverter profile SHALL support an optional `metadata.status` field whose allowed values are `tested` and `community`. When the field is absent the status SHALL be `community`.

#### Scenario: Status declared
- **WHEN** a profile declares `status: tested`
- **THEN** the loaded profile reports status `tested`

#### Scenario: Status absent
- **WHEN** a profile does not declare `status`
- **THEN** the loaded profile reports status `community`

#### Scenario: Invalid status rejected
- **WHEN** a profile declares a status other than `tested` or `community`
- **THEN** profile validation fails with an error naming the allowed values

### Requirement: Status exposed by the profiles API
`GET /api/profiles` SHALL include the status of every listed profile as a `status` string.

#### Scenario: Listing profiles
- **WHEN** a client requests `GET /api/profiles`
- **THEN** each entry contains `status` equal to `tested` or `community`

### Requirement: Shipped profiles are marked tested
Every profile shipped in `profiles/` (deye, fronius, sungrow, generic) SHALL declare `status: tested`, and `profiles/schema.yaml` SHALL document the field.

#### Scenario: Shipped profile listing
- **WHEN** the shipped profiles are listed
- **THEN** all of them report status `tested`

### Requirement: Status badge in profile pickers
The onboarding profile picker and the Settings profile picker SHALL show a badge with the status of the selected profile, using the design system badge classes. A missing status from an older backend SHALL be shown as `community`.

#### Scenario: Tested profile selected
- **WHEN** a profile with status `tested` is selected in either picker
- **THEN** a "Tested" badge is shown

#### Scenario: Community profile selected
- **WHEN** a profile with status `community`, or no status, is selected
- **THEN** a "Community" badge is shown

### Requirement: New profiles start as community
The profile authoring guide SHALL state that new contributed profiles start as `community` and are promoted to `tested` by a maintainer after hardware verification.

#### Scenario: Reading the guide
- **WHEN** a contributor reads the profile creation guide
- **THEN** it explains the `status` field and the community starting point
