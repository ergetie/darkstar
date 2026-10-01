## ADDED Requirements

### Requirement: Inverter profile switch always applies on reload
On config reload, the executor SHALL load the newly configured inverter profile whenever the resolved profile name differs from the currently loaded one, regardless of profile file modification times. It SHALL also reload when the name is unchanged but that profile file's mtime has changed. A null, empty or missing `system.inverter_profile` SHALL resolve to `generic` during reload, as it does at startup.

#### Scenario: Switch between profiles with identical file mtimes
- **WHEN** the loaded profile is `generic`, the config is saved with `inverter_profile: deye`, and `profiles/generic.yaml` and `profiles/deye.yaml` have identical mtimes
- **THEN** after the next reload the active profile SHALL be `deye`
- **AND** the executor status SHALL report `deye` with no profile error

#### Scenario: Null profile on reload
- **WHEN** the config is reloaded with `inverter_profile: null`
- **THEN** the active profile SHALL be `generic`
- **AND** no path named after the null value (e.g. `profiles/None.yaml`) SHALL be consulted

#### Scenario: Same profile file edited
- **WHEN** the profile name is unchanged and its profile file's mtime changes
- **THEN** the profile SHALL be reloaded from disk
