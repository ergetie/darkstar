## Purpose

Sensor data validation capability for detecting and handling anomalous sensor readings before they corrupt historical data or skew ML training.

## Requirements

### Requirement: Config-derived energy threshold
The system SHALL derive a maximum reasonable energy value per 15-minute slot from the configured grid power limit.

#### Scenario: Threshold calculated from grid max power
- **WHEN** `system.grid.max_power_kw` is configured as `8.0`
- **THEN** the system SHALL calculate `max_kwh_per_slot = 8.0 × 0.25 × 2.0 = 4.0 kWh`

#### Scenario: Missing config key raises an error
- **WHEN** `system.grid.max_power_kw` is not present in config
- **THEN** `get_max_energy_per_slot` SHALL raise a `ValueError` with a descriptive message
- **AND** callers SHALL propagate or log the error rather than silently proceeding
- **EXCEPTION**: The live recorder MAY store unvalidated data with a warning rather than dropping observations, since data preservation is prioritized over validation in the live recording path

### Requirement: Spike detection and handling
The system SHALL detect and handle sensor values that exceed physically reasonable limits.

#### Scenario: Spike value set to zero
- **WHEN** an energy value exceeds `max_kwh_per_slot`
- **THEN** the system SHALL set the value to `0.0`
- **AND** the system SHALL log a warning with the field name and detected value

#### Scenario: Valid value preserved
- **WHEN** an energy value is at or below `max_kwh_per_slot`
- **THEN** the system SHALL preserve the value unchanged

### Requirement: Validation before database storage
The recorder SHALL validate all energy values before storing to `slot_observations`.

#### Scenario: All energy fields validated
- **WHEN** the recorder prepares a record for storage
- **THEN** the system SHALL validate: `pv_kwh`, `load_kwh`, `import_kwh`, `export_kwh`, `water_kwh`, `ev_charging_kwh`, `batt_charge_kwh`, `batt_discharge_kwh`

#### Scenario: Battery charge/discharge validation
- **WHEN** `batt_charge_kwh` or `batt_discharge_kwh` exceeds `max_kwh_per_slot`
- **THEN** the system SHALL set the value to `0.0`

### Requirement: Solar health check reads array list
When `system.has_solar` is true, the health checker SHALL read `system.solar_arrays` (a list) and consider solar configured if any entry has `kwp > 0`. It SHALL NOT read `system.solar_array` (singular legacy key).

#### Scenario: Multi-array config passes health check
- **WHEN** `system.has_solar = true` and `system.solar_arrays` contains two entries each with `kwp > 0`
- **THEN** no "Solar enabled but panel size not configured" warning is emitted

#### Scenario: Empty arrays list triggers warning
- **WHEN** `system.has_solar = true` and `system.solar_arrays` is empty or absent
- **THEN** the warning "Solar enabled but panel size not configured" is emitted

#### Scenario: Legacy singular key is ignored
- **WHEN** `system.solar_array.kwp = 10.0` exists but `system.solar_arrays` is absent
- **THEN** the warning is still emitted (legacy key is not read)

### Requirement: Water heater health check reads heater list
When `system.has_water_heater` is true, the health checker SHALL read `water_heaters` (a list) and consider water heating configured if any enabled entry has `power_kw > 0`. It SHALL NOT read `water_heating.power_kw` (flat legacy field).

#### Scenario: Per-heater config passes health check
- **WHEN** `system.has_water_heater = true` and `water_heaters` contains an entry with `enabled = true` and `power_kw = 1`
- **THEN** no "Water heater enabled but power not configured" warning is emitted

#### Scenario: No heaters with power triggers warning
- **WHEN** `system.has_water_heater = true` and `water_heaters` is empty or all entries have `power_kw = 0`
- **THEN** the warning "Water heater enabled but power not configured" is emitted

#### Scenario: Legacy flat field is ignored
- **WHEN** `water_heating.power_kw = 3.0` exists but `water_heaters` list is empty
- **THEN** the warning is still emitted (legacy flat field is not read)

### Requirement: Water heater validation and warnings are skipped when the flag is off
When `system.has_water_heater` is `false`, the health checker, config save validation (including heater control-type and target-entity pairing checks and disabled-heater warnings), planner config check and `validate_water_heating_config` SHALL NOT emit warnings or errors derived from `water_heaters[]` or `water_heating.*`, and stale invalid heater values SHALL NOT block planning or saving.

#### Scenario: Invalid stale heater value with flag off
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters[0].max_hours_between_heating` is `-1`
- **WHEN** config is validated for planning or save
- **THEN** no water validation error is raised

#### Scenario: Same value with flag on
- **GIVEN** `system.has_water_heater` is `true`
- **THEN** the validation error is raised as before

#### Scenario: No water health issues with flag off
- **GIVEN** the flag is `false` and an enabled heater lacks a `sensor` or `power_kw`
- **WHEN** health is checked
- **THEN** no water-related issue is reported

#### Scenario: Heater pairing mismatch with flag off
- **GIVEN** the flag is `false` and a heater has `control_type: temperature` with a `switch.` target entity
- **WHEN** config is validated for save
- **THEN** no pairing error or warning is raised
