# Spec: Addon Secrets Preservation

## Purpose
Ensure add-on starts never destroy user secrets or silently override user configuration.

## Requirements

### Requirement: Secrets preserved on start
Add-on start SHALL only set `home_assistant.token` (always) and `home_assistant.url` (when missing or empty) in `secrets.yaml`, preserving every other key and comment, and SHALL NOT create a `notifications` section.

#### Scenario: Webhook preserved
- **WHEN** `secrets.yaml` holds a Discord webhook and an OpenRouter key and the add-on starts
- **THEN** both remain and the token is updated

#### Scenario: User URL kept
- **WHEN** `home_assistant.url` is already non-empty
- **THEN** it is not changed

#### Scenario: Unparseable file
- **WHEN** `secrets.yaml` exists but cannot be parsed
- **THEN** it is not rewritten and an error is logged

### Requirement: Only schema options applied
Add-on start SHALL apply only options in the add-on schema (`timezone`, `log_level`). The timezone SHALL overwrite `config.yaml` only when set to a non-empty value.

#### Scenario: Timezone unset
- **WHEN** the timezone option is absent or empty
- **THEN** `config.yaml` timezone is unchanged and no `TZ` is exported

#### Scenario: Timezone set
- **WHEN** the option is `Europe/Oslo`
- **THEN** `config.yaml` timezone becomes `Europe/Oslo`
