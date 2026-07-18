## ADDED Requirements

### Requirement: Null inverter profile falls back to generic without error
When `system.inverter_profile` is null, empty, or missing (the shipped default in `config.default.yaml`), inverter profile loading SHALL resolve directly to the `generic` profile with at most an INFO-level log line, and SHALL NOT attempt to load a profile file named after the null value (e.g. `profiles/None.yaml`) or emit an ERROR-level log. An explicitly configured profile name that cannot be found SHALL keep the existing behavior: WARNING-level log and fallback to `generic`.

#### Scenario: Fresh install boots clean
- **WHEN** the application starts with the shipped default configuration (`inverter_profile: null`)
- **THEN** the `generic` profile is loaded, no attempt is made to open `profiles/None.yaml`, and no ERROR-level log line is produced by profile loading

#### Scenario: Misspelled profile still warns
- **WHEN** `system.inverter_profile` is set to a non-empty name with no matching profile file
- **THEN** a WARNING is logged and the `generic` profile is used (unchanged behavior)
