## ADDED Requirements

### Requirement: Custom load power fields
A `custom_entity` load in `load_balancing.loads[]` SHALL accept optional `power_kw` (positive number) and `power_sensor` (HA entity ID). Both default to unset, so existing configs load unchanged without migration. The settings UI SHALL show both fields on the custom load row with help text that explains how they are used for restore decisions (live sensor, then configured power, then worst-case fallback). Validation SHALL reject non-positive `power_kw` with an actionable error.

#### Scenario: Existing custom load
- **WHEN** a config has a custom load without the new fields
- **THEN** it SHALL load without error and use the worst-case restore fallback

### Requirement: Coordination and anti-wear settings
The settings UI SHALL expose `max_step_interval_s`, `write_deadband_percent`, `pending_timeout_s`, `phase_sign` and per-load `min_on_s`/`min_off_s` in the load balancing section using the design-system components, with help text. `config.default.yaml` SHALL document each with a comment and its default. The UI SHALL NOT show `replan_after_throttled_s`.

#### Scenario: Defaults documented
- **WHEN** a user opens a fresh config
- **THEN** each new key has a commented default in `config.default.yaml` and a help text in the settings UI

## MODIFIED Requirements

### Requirement: Load balancing configuration schema
The config SHALL support: `system.grid.main_fuse_a` (positive integer, per-phase fuse rating in ampere); `input_sensors.grid_current_l1/l2/l3` (HA entity IDs for per-phase grid current or power at the connection point — the value SHALL be auto-detected as a current or power sensor per the `phase-load-balancing` capability). The key naming, voltage sensors, the `load_balancing` section keys, `loads[]` and `give_way_order[]` are specified in the scenarios below.

#### Scenario: grid_current key names kept for power sensors
- **WHEN** a power sensor is configured under `input_sensors.grid_current_l1/l2/l3`
- **THEN** the config key names SHALL remain `grid_current_l*` for backward compatibility

#### Scenario: Grid voltage sensors and load_balancing section keys
- **WHEN** the load-balancing configuration is read
- **THEN** `input_sensors.grid_voltage_l1/l2/l3` SHALL be supported as optional HA entity IDs for per-phase grid voltage, used only to convert a power-mode phase to current
- **AND** a `load_balancing` section SHALL support `enabled` (bool, default false), `resume_delay_s` (default 120), `resume_margin_percent` (default 90), `increase_step_a` (default 1), `sensor_stale_after_s` (default 30), `nominal_voltage_v` (default 220, used to convert a power-mode phase to current when that phase has no configured voltage entity), `notify_interventions` (bool, default false), `max_step_interval_s` (default 30), `write_deadband_percent` (default 2), `pending_timeout_s` (default 60) and `phase_sign` (`import_positive` default or `import_negative`); `replan_after_throttled_s` is no longer supported

#### Scenario: Load entries and give-way order list
- **WHEN** `load_balancing.loads[]` and `give_way_order[]` are configured
- **THEN** each `loads[]` entry SHALL be a device reference to a water heater, custom entity, or `type: binary` EV charger, plus a `phases` list; a custom entity MAY carry an optional `power_kw` and an optional `power_sensor` entity, and any entry MAY carry `min_on_s` and `min_off_s` (default 300 each)
- **AND** `type: current` EV chargers SHALL NOT be referenced in `loads[]`, and entries SHALL NOT carry a priority field
- **AND** `give_way_order[]` SHALL be an ordered list of references (`{kind: charger, id}` for a `type: current` EV charger, `{kind: shed, id}` for a `loads[]` entry) where the top entry gives way first

#### Scenario: Legacy priority keys migrated to give_way_order
- **WHEN** the config contains the previous `load_balancing.charger_priority` map or `loads[].priority` field
- **THEN** they are replaced by `give_way_order` and SHALL be migrated automatically at startup: chargers ordered by their old `charger_priority` (falling back to `ev_chargers[]` position), followed by `loads[]` entries ordered by their old `priority` ascending; the old keys are then dropped
- **AND** the migration SHALL be idempotent and logged

#### Scenario: give_way_order self-healing on config load
- **WHEN** the config is loaded
- **THEN** `give_way_order` SHALL be self-healed: current-type chargers absent from the list are appended after the last charger entry (or at the top if none), and `loads[]` entries absent from the list are appended at the end
- **AND** entries referencing missing devices (or chargers no longer `type: current`) are dropped with a logged warning
- **AND** `system.grid.max_power_kw` SHALL remain unchanged in meaning and use

#### Scenario: Defaults are safe
- **WHEN** a user upgrades without touching config
- **THEN** `load_balancing.enabled` SHALL be false and no behavior changes

#### Scenario: Fuse rating is independent of planner budget
- **WHEN** `main_fuse_a: 20` and `max_power_kw: 8` are both set
- **THEN** the planner SHALL keep using 8 kW as its import budget while the balancer uses 20 A per phase

#### Scenario: Existing current-sensor-only config is unaffected
- **WHEN** a config has only `input_sensors.grid_current_l1/l2/l3` set (no voltage entities, no `nominal_voltage_v` override)
- **THEN** all three phases SHALL resolve to current-sensor mode exactly as before this change
- **AND** `nominal_voltage_v` SHALL default to 220 without needing to be set

#### Scenario: Power sensor configured for a phase
- **WHEN** `input_sensors.grid_current_l1` points to an entity reporting Watts
- **THEN** that phase SHALL resolve to power-sensor mode and use `input_sensors.grid_voltage_l1` if set, else `load_balancing.nominal_voltage_v`

#### Scenario: A type: current charger cannot be added to loads[]
- **WHEN** a user attempts to add an EV charger with `type: current` to `load_balancing.loads[]`
- **THEN** config validation SHALL reject the entry (see "Startup validation with actionable errors")

#### Scenario: Old priority fields are migrated to give_way_order
- **WHEN** a config with `charger_priority: {ev_a: 1, ev_b: 2}` and `loads[]` entries with priorities 1 and 2 is loaded after upgrade
- **THEN** `give_way_order` SHALL be `[charger ev_a, charger ev_b, shed (old priority 1), shed (old priority 2)]`
- **AND** `charger_priority` and every `loads[].priority` SHALL be removed
- **AND** balancer behavior SHALL be identical to the previous two-tier system

#### Scenario: Newly added charger self-heals into the order
- **WHEN** a new `type: current` charger is added to `ev_chargers[]` without touching `give_way_order`
- **THEN** the next config load SHALL append it after the last charger entry in `give_way_order` and log the addition

#### Scenario: Charger switched back to binary drops out of the order
- **WHEN** a charger referenced in `give_way_order` is changed to `type: binary`
- **THEN** the next config load SHALL drop that entry with a logged warning
