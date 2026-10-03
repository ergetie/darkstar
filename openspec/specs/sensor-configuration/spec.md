# Sensor Configuration

## Purpose

Configuration for Home Assistant sensors and input sensors.
## Requirements
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

### Requirement: EV charger energy_sensor configuration removed
The `energy_sensor` field SHALL NOT be supported for `ev_chargers[]` items. EV energy recording MUST use the HA History API with the existing power sensor (`sensor` field). Config migration SHALL silently remove `energy_sensor` from `ev_chargers[]` items — no user action required.

#### Scenario: Config migration removes energy_sensor from EV chargers
- **WHEN** an existing config contains `energy_sensor` in an `ev_chargers[]` item
- **THEN** the migration SHALL remove the `energy_sensor` field
- **AND** the migration SHALL NOT affect other fields in the EV charger config

#### Scenario: Default config excludes energy_sensor for EV chargers
- **WHEN** a new user installs Darkstar
- **THEN** the default config SHALL NOT include `energy_sensor` in `ev_chargers[]` items

### Requirement: Water heater energy_sensor configuration removed
The `energy_sensor` field SHALL NOT be supported for `water_heaters[]` items. Water heater energy recording MUST use the HA History API with the existing power sensor (`sensor` field). Config migration SHALL silently remove `energy_sensor` from `water_heaters[]` items — no user action required.

#### Scenario: Config migration removes energy_sensor from water heaters
- **WHEN** an existing config contains `energy_sensor` in a `water_heaters[]` item
- **THEN** the migration SHALL remove the `energy_sensor` field
- **AND** the migration SHALL NOT affect other fields in the water heater config

#### Scenario: Default config excludes energy_sensor for water heaters
- **WHEN** a new user installs Darkstar
- **THEN** the default config SHALL NOT include `energy_sensor` in `water_heaters[]` items

### Requirement: No health check warnings for missing energy_sensor (EV/Water)
The health check SHALL NOT warn about missing `energy_sensor` for EV chargers or water heaters, as this field no longer exists.

#### Scenario: No health warning for missing EV energy_sensor
- **WHEN** the health check evaluates an enabled EV charger
- **THEN** it SHALL NOT warn about missing `energy_sensor`

#### Scenario: No health warning for missing water heater energy_sensor
- **WHEN** the health check evaluates an enabled water heater
- **THEN** it SHALL NOT warn about missing `energy_sensor`

### Requirement: Settings UI removes energy_sensor for EV and Water
The Settings user interface SHALL NOT display the `energy_sensor` configuration field for EV chargers or water heaters.

#### Scenario: EV charger settings exclude energy_sensor
- **WHEN** a user navigates to Settings > EV
- **THEN** the entity array editor for EV chargers SHALL NOT display an `energy_sensor` field

#### Scenario: Water heater settings exclude energy_sensor
- **WHEN** a user navigates to Settings > Water
- **THEN** the entity array editor for water heaters SHALL NOT display an `energy_sensor` field

### Requirement: Profile entity fields are displayed in category-appropriate tab
The Settings UI SHALL display profile entity fields only in the tab matching the entity's `category` field. Entities with `category: "system"` SHALL appear in the System tab. Entities with `category: "battery"` SHALL appear in the Battery tab. No entity SHALL appear in both tabs.

#### Scenario: System tab shows only system-category entities
- **WHEN** a user selects an inverter profile (e.g., Fronius, Deye, Sungrow, Generic)
- **AND** navigates to Settings > System > "Required HA Control Entities"
- **THEN** only entities with `category: "system"` from that profile SHALL be displayed
- **AND** entities with `category: "battery"` SHALL NOT be displayed

#### Scenario: Battery tab shows only battery-category entities
- **WHEN** a user selects an inverter profile
- **AND** navigates to Settings > Battery > "HA Control Entities"
- **THEN** only entities with `category: "battery"` from that profile SHALL be displayed
- **AND** entities with `category: "system"` SHALL NOT be displayed

### Requirement: Custom entity keys use consistent config paths
All dynamic entity field generation SHALL use the `standardInverterKeys` set to determine config key paths. Standard entity keys SHALL map to `executor.inverter.{key}`. Non-standard (custom) entity keys SHALL map to `executor.inverter.custom_entities.{key}`. This mapping MUST be consistent between the rendered field components and the form state management.

#### Scenario: Custom battery entity change is detected as dirty
- **WHEN** a user changes a non-standard battery entity field (e.g., Fronius `grid_discharge_power`)
- **THEN** the form SHALL detect the change as dirty
- **AND** the save mechanism SHALL be available

#### Scenario: Custom entity value is saved to correct config path
- **WHEN** a user sets a non-standard entity field to a value and saves
- **THEN** the value SHALL be persisted at `executor.inverter.custom_entities.{key}` in the config
- **AND** the value SHALL be loaded correctly when the page is revisited

### Requirement: All settings tabs have a dedicated save button
Every settings tab SHALL include an always-visible save button at the bottom of the tab content, in addition to the sticky `UnsavedChangesBanner`. The save button SHALL be present regardless of whether changes have been made.

#### Scenario: Battery tab has a save button
- **WHEN** a user navigates to Settings > Battery
- **THEN** a "Save Battery Settings" button SHALL be visible at the bottom of the tab

#### Scenario: Solar tab has a save button
- **WHEN** a user navigates to Settings > Solar
- **THEN** a "Save Solar Settings" button SHALL be visible at the bottom of the tab

#### Scenario: Water tab has a save button
- **WHEN** a user navigates to Settings > Water
- **THEN** a "Save Water Settings" button SHALL be visible at the bottom of the tab

#### Scenario: EV tab has a save button
- **WHEN** a user navigates to Settings > EV
- **THEN** a "Save EV Settings" button SHALL be visible at the bottom of the tab

#### Scenario: Parameters tab has a save button
- **WHEN** a user navigates to Settings > Parameters
- **THEN** a "Save Parameter Settings" button SHALL be visible at the bottom of the tab

#### Scenario: Save button shows saving state
- **WHEN** a user clicks the save button on any settings tab
- **THEN** the button text SHALL change to "Saving..." while the save is in progress
- **AND** the button SHALL be disabled during the save operation

### Requirement: Default config does not include placeholder sensor entities
The default configuration template (`config.default.yaml`) SHALL NOT include placeholder sensor entity names for optional subsystems. The `water_heaters[].sensor` field SHALL default to an empty string (`''`) rather than a specific entity name like `sensor.vvb_power`.

#### Scenario: New installation has no phantom water heater sensor
- **WHEN** a new user installs Darkstar
- **AND** the default config is generated from `config.default.yaml`
- **THEN** the `water_heaters[0].sensor` field is `''` (empty string)
- **AND** no HTTP requests are made for non-existent water heater entities

### Requirement: Config help tooltips document soft vs hard bounds clearly
The configuration help text (`frontend/src/config-help.json`) SHALL document `battery.max_soc_percent` and `system.battery.max_soc_percent` as **soft** ceilings — a preference the solver penalizes overshooting but tolerates when the battery is already above the limit at planning time.

The tooltip SHALL explicitly state that (a) the BMS enforces the absolute physical limit, (b) the solver treats this value as a target ceiling, and (c) starting the plan above the ceiling results in a discharge action, not a failure.

The comments in `config.default.yaml` next to `max_soc_percent` SHALL be updated with the same guidance.

#### Scenario: Tooltip describes soft semantics
- **WHEN** a user hovers the help indicator for `battery.max_soc_percent` in Settings
- **THEN** the tooltip text explicitly contains the words "soft" or "preference" (or equivalent phrasing)
- **AND** the tooltip states that exceeding the value does not cause planner failure

#### Scenario: Default config comment matches tooltip
- **WHEN** a user opens `config.default.yaml`
- **THEN** the comment adjacent to `max_soc_percent` reflects the soft semantics described in the tooltip

### Requirement: EV charger max_power_kw tooltip is explicit about requirement
The configuration help text for the per-charger `max_power_kw` field SHALL explicitly state that the field is **required**, SHALL give one or more example values (e.g., 7.4, 11, 22 kW), and SHALL warn that leaving it blank or setting it to zero causes the charger to be registered as disabled.

#### Scenario: EV power tooltip states requirement and example
- **WHEN** a user opens the EV charger editor and hovers the help indicator for `max_power_kw`
- **THEN** the tooltip text contains the word "required" (or equivalent phrasing)
- **AND** the tooltip includes at least one example value
- **AND** the tooltip warns that a missing or zero value disables the charger

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
