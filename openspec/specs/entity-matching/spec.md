# entity-matching Specification

## Purpose
Provide declarative entity matching, inverter detection and ranked configuration suggestions for onboarding.

## Requirements

### Requirement: Profiles declare match rules
Each inverter profile entity MAY declare a `match` block with keys `integration`, `domain`, `device_class`, `unit`, `entity_id_regex` and `name_regex`. A profile MAY declare `metadata.detect` with `integrations` and `manufacturers`. Profile loading SHALL reject unknown match keys and invalid regexes.

#### Scenario: Invalid regex rejected
- **WHEN** a profile declares `entity_id_regex: "("`
- **THEN** profile validation SHALL fail with an error naming the profile and entity key

#### Scenario: Shipped profiles carry rules
- **WHEN** the shipped profiles are loaded
- **THEN** every required entity in `deye`, `fronius`, `sungrow` SHALL have a `match` block
- **AND** the `fronius` profile SHALL NOT contain installation-specific `default_entity` values

### Requirement: Profile behavior keys are parsed
Profile parsing SHALL read every behavior key used by shipped profiles, including `write_threshold_a`.

#### Scenario: Deye write threshold honoured
- **WHEN** the deye profile declares `write_threshold_a`
- **THEN** the parsed profile behavior SHALL carry that value instead of the code default

### Requirement: Inverter brand suggestion
The system SHALL rank available profiles against discovered entities using `metadata.detect`, returning the best match with a confidence.

#### Scenario: Deye integration detected
- **WHEN** discovery contains entities from an integration listed in deye's `detect.integrations`
- **THEN** `deye` SHALL be ranked first

#### Scenario: No match
- **WHEN** no profile's detect rules match
- **THEN** no brand SHALL be suggested and `generic` SHALL be offered as fallback

### Requirement: Ranked candidates per config path
The system SHALL score discovered entities against profile match rules and built-in role rules (core sensors, water heater, EV), and return for each config path up to 5 candidates with `entity_id`, `score`, `confidence` (`high|medium|low`) and `reasons`. Domain SHALL be a hard filter. Every other match rule SHALL independently add points according to the single weights table; a non-matching rule SHALL NOT exclude an otherwise eligible candidate.

#### Scenario: High-confidence pick
- **WHEN** exactly one entity matches integration, device_class and unit for `input_sensors.battery_soc`
- **THEN** it SHALL be returned first with `confidence: "high"`

#### Scenario: Ambiguous pick
- **WHEN** two entities score within the confidence margin
- **THEN** neither SHALL be `high` confidence

#### Scenario: Domain hard filter
- **WHEN** an entity's domain is not allowed for the path
- **THEN** it SHALL NOT appear as a candidate

#### Scenario: Partial match scores independently
- **WHEN** an entity matches device_class and unit but not integration
- **THEN** it SHALL receive the device_class and unit points and remain eligible if its score meets the threshold

### Requirement: Suggestions returned as nested patch with current values
`GET /api/profiles/{name}/suggestions` and `GET /api/setup/suggestions` SHALL return `patch` (nested config containing only high-confidence picks), `candidates` (keyed by dotted path), `current` (existing config values for the same paths) and `missing_required`. The response SHALL NOT contain flat dotted keys in `patch`.

#### Scenario: Patch is nested
- **WHEN** the suggestion for `executor.inverter.work_mode` is high confidence
- **THEN** `patch` SHALL contain `{"executor": {"inverter": {"work_mode": "<entity>"}}}`

#### Scenario: Existing value reported
- **WHEN** `executor.inverter.work_mode` is already configured
- **THEN** `current["executor.inverter.work_mode"]` SHALL contain the configured value

#### Scenario: Unmatched required entity
- **WHEN** a required profile entity has no candidate
- **THEN** its path SHALL be listed in `missing_required`

### Requirement: Config comment lists only shipped profiles
The `system.inverter_profile` comment in `config.default.yaml` SHALL list only profiles that exist in `profiles/`.

#### Scenario: Victron not listed
- **WHEN** no `profiles/victron.yaml` exists
- **THEN** the comment SHALL NOT mention `victron`
