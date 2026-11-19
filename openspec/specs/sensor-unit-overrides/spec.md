# Spec: Sensor Unit Overrides

## Purpose
Make power-sensor unit handling explicit and visible: sensors without a unit keep working as kW, but the user is told and can declare W or kW.

## Requirements

### Requirement: Unit override configuration
The configuration SHALL support `sensor_unit_overrides`, a map of entity id to `W` or `kW`, defaulting to empty. Any other value or a key that is not an entity id SHALL be rejected on save with a clear error.

#### Scenario: Invalid override rejected
- **WHEN** config is saved with `sensor_unit_overrides: {sensor.x: "MW"}`
- **THEN** the save fails with an error naming the entry

### Requirement: Single unit resolution
Every site that converts a power reading to kW SHALL use one resolver: the unit reported by Home Assistant wins, else the override, else kW is assumed (current behaviour, so existing installs keep working). Reported W, kW and MW SHALL convert consistently everywhere.

#### Scenario: Reported unit wins
- **WHEN** HA reports `W` and the override says `kW`
- **THEN** the value is divided by 1000

#### Scenario: Override used for unitless sensor
- **WHEN** HA reports no unit and the override is `W`
- **THEN** the value is divided by 1000

#### Scenario: Unitless without override keeps working
- **WHEN** HA reports no unit and no override exists
- **THEN** the value is read as kW, and a warning naming the entity and the fix is logged once per entity

#### Scenario: EV power converted
- **WHEN** an EV charger power sensor reports 7200 W
- **THEN** system status shows 7.2 kW

### Requirement: Backend reports sensors that need a unit
The backend SHALL list every configured numeric power sensor whose live HA state has no unit, with or without an override, as entries `{entity_id, settings_path, live_value, override}` where `override` is `"W"`, `"kW"` or `null`, in the readiness response (`unit_needed`) and for a draft config via a lightweight endpoint that does not run the planner.

#### Scenario: Readiness warning
- **WHEN** a sensor is listed in `unit_needed`
- **THEN** readiness shows the warning "no unit reported by Home Assistant. Choose W or kW for this sensor." with action `set_sensor_unit`

#### Scenario: Override set
- **WHEN** the sensor has an override
- **THEN** it is still listed with that `override`, and the readiness check passes and notes the manual unit (no warning)

#### Scenario: Unitless sensor listed
- **WHEN** a configured power sensor has numeric state, no HA unit and no override
- **THEN** it is listed in `unit_needed` with `override: null` and readiness shows the action-needed warning

#### Scenario: Unit reported
- **WHEN** HA reports a unit for the sensor
- **THEN** it is not listed

#### Scenario: Draft config
- **WHEN** the draft-config endpoint receives a config where a different entity is selected
- **THEN** the list reflects the draft selection

### Requirement: Unit selector in the shared entity picker
The shared entity picker used in onboarding and in Settings SHALL show a W/kW selector exactly when its currently selected entity is in the backend `unit_needed` list, preselected with the listed `override`, so a saved choice stays visible and changeable after a reload, SHALL refresh that list when the selection changes, and SHALL store the choice as the `sensor_unit_overrides` map entry for that entity id (written as the whole map). The UI SHALL NOT contain a list of power-sensor fields.

#### Scenario: Selector appears and disappears
- **WHEN** the user selects a unitless sensor and then another sensor that reports a unit
- **THEN** the selector appears for the first and disappears for the second

#### Scenario: Saved choice survives reload
- **WHEN** the user saved `W` for a unitless sensor and reopens the page
- **THEN** the selector is shown with `W` preselected

#### Scenario: Works in both places
- **WHEN** the same entity is selected in onboarding or in the Settings page
- **THEN** the selector behaves identically

### Requirement: Sensors with a unit are unchanged
For entities that report a unit, the picker SHALL show "Current value: <state> <unit>" with no selector, exactly as before.

#### Scenario: Unit reported
- **WHEN** the selected sensor reports `W`
- **THEN** "Current value: 1200 W" is shown and no selector is shown
