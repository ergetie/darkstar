## MODIFIED Requirements

### Requirement: Excess PV sink configuration in Advanced tab

The Settings UI SHALL provide a priority-list editor in the Advanced tab under "Excess PV Dispatch". Users SHALL be able to add, remove, and reorder (move up/down) sink entries of type "EV Surplus Charging", "Water Heater Boost", and "Custom Entity". List order is priority order (first = fed first); the UI SHALL state that the house battery is always first. Each entry SHALL show its per-type configuration fields in a collapsible panel. Shared fields (`boost_reward_sek_per_kwh`, `soc_threshold_percent`) SHALL appear once below the list.

#### Scenario: User with water heater sees all three entry types
- **WHEN** system configuration has `has_water_heater=true` and a current-type EV charger exists
- **THEN** the add-entry selector SHALL offer "EV Surplus Charging", "Water Heater Boost", and "Custom Entity"

#### Scenario: User without water heater cannot add a boost entry
- **WHEN** system configuration has `has_water_heater=false`
- **THEN** the add-entry selector SHALL NOT offer "Water Heater Boost"

#### Scenario: EV entry requires a current-type charger
- **WHEN** no EV charger with `type: current` is configured
- **THEN** the add-entry selector SHALL NOT offer "EV Surplus Charging"
- **AND** the UI SHALL hint that variable current control must be enabled on a charger first

#### Scenario: Reordering entries changes priority
- **WHEN** the user moves the "EV Surplus Charging" entry above "Water Heater Boost" and saves
- **THEN** the persisted priority array SHALL list the `ev` entry before the `water_heater_boost` entry

#### Scenario: Custom entity entry shows its configuration
- **WHEN** a "Custom Entity" entry is added
- **THEN** fields SHALL appear for entity ID, on-value, off-value, and power (kW, default 1.0)
- **AND** entity ID validation SHALL reject empty values

#### Scenario: EV entry shows its configuration
- **WHEN** an "EV Surplus Charging" entry is added
- **THEN** a charger selector (from configured current-type chargers) and a surplus deadband field (kW, default 0.2) SHALL appear

#### Scenario: Empty list disables the feature
- **WHEN** the priority list has no entries
- **THEN** the UI SHALL indicate that excess-PV dispatch is disabled
- **AND** the system SHALL NOT schedule or execute any excess PV actions

### Requirement: Excess PV config saved and loaded from config.yaml

The excess PV configuration SHALL be persisted to `config.yaml` under `executor.excess_pv.priority` (ordered array of typed sink entries) plus shared keys, and loaded at executor and planner startup. A config migration SHALL convert the legacy `executor.excess_pv.sink` key: `water_heater_boost` → `[{type: water_heater_boost}]`, `custom_entity` → a one-element array carrying the legacy custom-entity fields, `disabled` → `[]`; the legacy key SHALL be removed after migration and the migration SHALL be logged and idempotent.

#### Scenario: Config saved on settings change
- **WHEN** user reorders the priority list and saves
- **THEN** `executor.excess_pv.priority` SHALL be written to config.yaml in the new order

#### Scenario: Config loaded on startup
- **WHEN** the executor starts and `excess_pv.priority` contains an `ev` entry followed by a `water_heater_boost` entry
- **THEN** the executor and planner SHALL use that ordering for dispatch

#### Scenario: Legacy single-sink config migrated
- **WHEN** config.yaml contains `executor.excess_pv.sink: custom_entity` with a `custom_entity` block and no `priority` key
- **THEN** startup migration SHALL produce `priority: [{type: custom_entity, ...legacy fields}]`, remove the `sink` key, and log the migration

#### Scenario: Migration is idempotent
- **WHEN** the migration has already run and `priority` exists
- **THEN** a subsequent startup SHALL NOT modify the config again

## ADDED Requirements

### Requirement: Phase-switching settings on the EV charger device

The Settings UI SHALL provide phase-switching configuration on each current-type EV charger's device settings: `phase_mode_entity` (HA entity ID), `phase_switching.enabled` toggle (default off), `hysteresis_kw` (default 0.5), and `min_dwell_s` (default 600). The enabled toggle SHALL require a non-empty `phase_mode_entity`.

#### Scenario: Enabling phase switching without an entity is rejected
- **WHEN** the user enables phase switching with an empty `phase_mode_entity`
- **THEN** validation SHALL reject the save with a message naming the missing field

#### Scenario: Defaults applied when enabling
- **WHEN** the user sets a phase-mode entity and enables phase switching without touching other fields
- **THEN** `hysteresis_kw` SHALL default to 0.5 and `min_dwell_s` to 600
