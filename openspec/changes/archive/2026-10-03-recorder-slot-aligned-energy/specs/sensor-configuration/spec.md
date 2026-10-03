## ADDED Requirements

### Requirement: Cumulative energy counter keys removed
The configuration SHALL NOT support `input_sensors.total_pv_production`, `total_load_consumption`, `total_grid_import`, `total_grid_export`, `total_battery_charge`, `total_battery_discharge`, `recorder.max_meter_delta_kwh` or `learning.sensor_map`. Startup config migration SHALL remove these keys from existing configs silently and idempotently, after the legacy numeric `total_load_consumption` value has been moved to `synthetic_daily_load_kwh`. The keys SHALL NOT be re-added by the default-template merge. The legacy `secrets.home_assistant.consumption_entity_id` fallback SHALL NOT be read.

#### Scenario: Existing config with counters
- **WHEN** a config contains all six `input_sensors.total_*` keys set to sensor entities
- **THEN** after startup migration none of the six keys SHALL be present
- **AND** all other `input_sensors` values SHALL be unchanged

#### Scenario: Keys are not restored by the template merge
- **WHEN** migration runs and the default template is merged afterwards
- **THEN** the removed keys SHALL still be absent

#### Scenario: Legacy numeric load value is preserved
- **WHEN** a config contains `total_load_consumption: "18"` and no `synthetic_daily_load_kwh`
- **THEN** after migration `synthetic_daily_load_kwh` SHALL be `18` and `total_load_consumption` SHALL be absent

#### Scenario: Migration is idempotent
- **WHEN** migration runs on an already-migrated config
- **THEN** it SHALL report no change

#### Scenario: Health does not require removed keys
- **WHEN** learning is enabled and none of the removed keys are present
- **THEN** the health check SHALL NOT report a missing sensor for any of them

## MODIFIED Requirements

### Requirement: Configuration schema removes today_* sensors
The configuration schema SHALL NOT require or support `today_*` sensors in the `input_sensors` section.

#### Scenario: Config validation rejects today_* sensors
- **WHEN** a configuration file contains any `today_*` sensor keys
- **THEN** the validation system rejects the configuration with a descriptive error message
- **AND** the error message names the offending keys and instructs the user to remove them

#### Scenario: Default config excludes today_* sensors
- **WHEN** a new user installs Darkstar
- **THEN** the default config.yaml does NOT include any `today_*` sensors
- **AND** the default config only includes power sensors for PV, load, grid and battery energy

### Requirement: Settings UI removes today_* sensor configuration
The Settings user interface SHALL NOT display configuration fields for `today_*` sensors or for cumulative energy counters.

#### Scenario: Settings page shows only power sensors for energy
- **WHEN** a user navigates to Settings > Input Sensors
- **THEN** the UI displays power sensor configuration for PV, load, grid and battery
- **AND** does NOT display fields for today_grid_import, today_grid_export, today_pv_production, today_load_consumption, today_battery_charge, today_battery_discharge, or today_net_cost
- **AND** does NOT display a "Lifetime Energy Totals" section or any `total_*` counter field

### Requirement: Config help documentation updates
The configuration help documentation SHALL remove all references to `today_*` sensors and to cumulative energy counters.

#### Scenario: Help text updated
- **WHEN** a user views configuration help
- **THEN** the documentation describes the power sensors as the required configuration for energy recording
- **AND** does NOT mention `today_*` sensors or `total_*` counter keys

## REMOVED Requirements

### Requirement: Cumulative energy sensor tooltips explain expected sensor shape
**Reason**: The six counter keys no longer exist.
**Migration**: Keys removed by startup migration; tooltips deleted from `config-help.json`.
