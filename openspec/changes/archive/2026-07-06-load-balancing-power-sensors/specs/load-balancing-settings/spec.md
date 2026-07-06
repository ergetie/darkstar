## MODIFIED Requirements

### Requirement: Load balancing configuration schema
The config SHALL support: `system.grid.main_fuse_a` (positive integer, per-phase fuse rating in ampere); `input_sensors.grid_current_l1/l2/l3` (HA entity IDs for per-phase grid current or power at the connection point — the value SHALL be auto-detected as a current or power sensor per the `phase-load-balancing` capability, and the config key names remain `grid_current_l*` for backward compatibility even when a power sensor is configured); `input_sensors.grid_voltage_l1/l2/l3` (optional HA entity IDs for per-phase grid voltage, used only to convert a power-mode phase to current); and a `load_balancing` section with `enabled` (bool, default false), `resume_delay_s` (default 120), `resume_margin_percent` (default 90), `increase_step_a` (default 1), `sensor_stale_after_s` (default 30), `nominal_voltage_v` (default 220, used to convert a power-mode phase to current when that phase has no configured voltage entity), and `loads[]` (each entry: device reference to a water heater, custom entity, or `type: binary` EV charger — `type: current` EV chargers SHALL NOT be referenced here, see the dynamically-throttled group below; `phases` list; `priority` integer). Every `type: current` EV charger SHALL automatically be a member of a separate, always-populated dynamically-throttled group, independent of `loads[]`. Its priority SHALL be stored in a new `load_balancing.charger_priority` map (charger id → priority integer); a charger with no entry in this map SHALL default to a priority derived from its position in `ev_chargers[]`. This keeps the new field entirely within the `load_balancing` schema rather than modifying the `ev_chargers[]` entry structure owned by the `per-device-ev-scheduling` capability. `system.grid.max_power_kw` SHALL remain unchanged in meaning and use.

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

### Requirement: Startup validation with actionable errors
When `load_balancing.enabled` is true, startup validation SHALL verify that `main_fuse_a` is set and positive, all three per-phase sensors are configured, and `loads[]` contains at least one entry referencing an existing device with a non-empty `phases` list, OR at least one `type: current` EV charger is configured (which is automatically balanced without needing a `loads[]` entry). Each violation SHALL produce an error naming the missing key and how to fix it. Implausible values (e.g. `main_fuse_a` > 125 or ≤ 0) SHALL be rejected.

For each configured per-phase sensor, validation SHALL confirm its unit resolves to a recognized current or power unit; an unrecognized unit SHALL fail validation naming the phase and the offending entity. If any phase resolves to power-sensor mode, `load_balancing.nominal_voltage_v` (or that phase's voltage entity) SHALL be available — since `nominal_voltage_v` always has a default, this SHALL never block validation on its own. Any `loads[]` entry referencing an EV charger whose `type` is `current` SHALL fail validation with a message directing the user to the dynamically-throttled group instead (no `loads[]` entry needed for that charger).

#### Scenario: Enabled without phase sensors
- **WHEN** `load_balancing.enabled: true` but `grid_current_l2` is missing
- **THEN** validation SHALL fail with a message naming `input_sensors.grid_current_l2`

#### Scenario: Load references unknown device
- **WHEN** a `loads[]` entry references an EV charger ID that does not exist in `ev_chargers[]`
- **THEN** validation SHALL fail naming the offending entry

#### Scenario: Enabled with only a dynamically-throttled charger and no loads[]
- **WHEN** `load_balancing.enabled: true`, no `loads[]` entries exist, but one `ev_chargers[]` entry has `type: current`
- **THEN** validation SHALL pass (the dynamically-throttled charger satisfies the "at least one balanced load" requirement)

#### Scenario: loads[] references a type: current charger
- **WHEN** a `loads[]` entry's `device_id` matches an `ev_chargers[]` entry with `type: current`
- **THEN** validation SHALL fail, naming the charger and explaining it is already balanced automatically and must not be listed in `loads[]`

#### Scenario: Sensor with unrecognized unit
- **WHEN** `input_sensors.grid_current_l1` points to an entity whose `unit_of_measurement` is not a recognized current or power unit
- **THEN** validation SHALL fail naming `input_sensors.grid_current_l1` and the unrecognized unit

### Requirement: Settings UI section
The frontend SHALL provide a load-balancing settings section with a global enable toggle, the fuse rating, per-phase sensor pickers (labeled to indicate either current or power sensors are accepted), anti-flap tuning fields, a nominal voltage field, and a restructured balanced-loads area split into two clearly labeled groups:
- **Dynamically Throttled Chargers**: every `type: current` EV charger, listed automatically (not user-added/removed), showing its name and configured phases read-only (sourced from the EV Chargers tab) plus an editable priority field. Section copy SHALL state these chargers are always throttled before anything in the group below is touched.
- **Shed as Last Resort**: the existing editable list (water heater, custom entity, `type: binary` EV charger), each with device, phases, and priority. Section copy SHALL state this group only activates once every charger in the group above is at its floor or paused.

If any phase resolves to power-sensor mode, the settings UI SHALL show all three per-phase voltage entity fields together as one group (not conditionally per individual phase), each optional and independently falling back to the nominal voltage if left blank. The section SHALL explain in plain language that phase assignment for on/off loads must match the physical installation.

#### Scenario: User enables the feature from the UI
- **WHEN** the user fills in fuse rating, sensors, and one load, then enables the toggle
- **THEN** the config SHALL be persisted through the existing config write path and validation feedback shown inline

#### Scenario: Power sensor reveals voltage fields
- **WHEN** the user selects a power-reporting entity for any of the three phase sensor fields
- **THEN** the settings UI SHALL show all three "Grid voltage sensor" fields together
- **AND** each SHALL be optional, independently

#### Scenario: EV charger picker no longer offers type: current chargers for shedding
- **WHEN** the user opens the "Shed as Last Resort" device picker for an EV charger entry
- **THEN** only `type: binary` EV chargers SHALL be offered
- **AND** every `type: current` EV charger SHALL instead appear, automatically, in the "Dynamically Throttled Chargers" group

### Requirement: Live per-phase status
The system SHALL expose live balancer status — per-phase measured current, fuse rating, headroom, and the balancer's current action — via the existing live-metrics WebSocket emission and a REST status endpoint. The status SHALL include one named entry per dynamically-throttled EV charger (charger name, state — idle/throttling/paused/stale-fallback, current setpoint vs. planned target) rather than a single unnamed summary line, plus the existing on/off shed-list state (which loads are shed, with reason). The frontend SHALL render a status view with per-phase load bars against the fuse limit, a per-charger row for each dynamically-throttled charger, and the active shed state with its reason.

#### Scenario: User watches the balancer act
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 is near the fuse limit
- **THEN** the status view SHALL show L1 near its limit and a row for that charger stating it's limited to 10 A (planned 16 A) because of L1

#### Scenario: Feature disabled
- **WHEN** `load_balancing.enabled` is false
- **THEN** the status view SHALL state the feature is disabled instead of showing empty bars

#### Scenario: Multiple dynamically-throttled chargers are individually visible
- **WHEN** two `type: current` EV chargers are configured and one is being throttled while the other charges at its planned target
- **THEN** the status view SHALL show two distinct named rows, one per charger, each reflecting its own state
