# Delta Spec: Load Balancing Settings (load-balancing-completion)

## MODIFIED Requirements

### Requirement: Load balancing configuration schema
The config SHALL support: `system.grid.main_fuse_a` (positive integer, per-phase fuse rating in ampere); `input_sensors.grid_current_l1/l2/l3` (HA entity IDs for per-phase grid current or power at the connection point — the value SHALL be auto-detected as a current or power sensor per the `phase-load-balancing` capability, and the config key names remain `grid_current_l*` for backward compatibility even when a power sensor is configured); `input_sensors.grid_voltage_l1/l2/l3` (optional HA entity IDs for per-phase grid voltage, used only to convert a power-mode phase to current); and a `load_balancing` section with `enabled` (bool, default false), `resume_delay_s` (default 120), `resume_margin_percent` (default 90), `increase_step_a` (default 1), `sensor_stale_after_s` (default 30), `nominal_voltage_v` (default 220, used to convert a power-mode phase to current when that phase has no configured voltage entity), `notify_interventions` (bool, default false), `replan_after_throttled_s` (default 600), `loads[]` (each entry: device reference to a water heater, custom entity, or `type: binary` EV charger — `type: current` EV chargers SHALL NOT be referenced here — plus a `phases` list; entries SHALL NOT carry a priority field), and `give_way_order[]` — an ordered list of references (`{kind: charger, id}` for a `type: current` EV charger, `{kind: shed, id}` for a `loads[]` entry) where the top entry gives way first.

The previous `load_balancing.charger_priority` map and `loads[].priority` field are replaced by `give_way_order` and SHALL be migrated automatically at startup: chargers ordered by their old `charger_priority` (falling back to `ev_chargers[]` position), followed by `loads[]` entries ordered by their old `priority` ascending; the old keys are then dropped. The migration SHALL be idempotent and logged. On every config load, `give_way_order` SHALL be self-healed: current-type chargers absent from the list are appended after the last charger entry (or at the top if none), `loads[]` entries absent from the list are appended at the end, and entries referencing missing devices (or chargers no longer `type: current`) are dropped with a logged warning. `system.grid.max_power_kw` SHALL remain unchanged in meaning and use.

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

### Requirement: Startup validation with actionable errors
When `load_balancing.enabled` is true, startup validation SHALL verify that `main_fuse_a` is set and positive, all three per-phase sensors are configured, and `loads[]` contains at least one entry referencing an existing device with a non-empty `phases` list, OR at least one `type: current` EV charger is configured (which is automatically balanced without needing a `loads[]` entry). Each violation SHALL produce an error naming the missing key and how to fix it. Implausible values (e.g. `main_fuse_a` > 125 or ≤ 0) SHALL be rejected.

For each configured per-phase sensor, validation SHALL confirm its unit resolves to a recognized current or power unit; an unrecognized unit SHALL fail validation naming the phase and the offending entity. If any phase resolves to power-sensor mode, `load_balancing.nominal_voltage_v` (or that phase's voltage entity) SHALL be available — since `nominal_voltage_v` always has a default, this SHALL never block validation on its own. Any `loads[]` entry referencing an EV charger whose `type` is `current` SHALL fail validation with a message directing the user to the give-way list instead (the charger appears there automatically).

Validation SHALL additionally emit non-blocking warnings (logged and surfaced in the settings UI, never failing startup): when `load_balancing.enabled` is true and `executor.interval_seconds` exceeds 15, a warning SHALL name both keys and state that the balancer reacts and reports only once per tick (recommended ≤ 15 s); and when any `type: current` EV charger has no `soc_sensor` configured, a warning SHALL name the charger and state that Darkstar cannot track its charging progress or recover throttling shortfall (plan-time SoC is assumed 0%).

#### Scenario: Enabled without phase sensors
- **WHEN** `load_balancing.enabled: true` but `grid_current_l2` is missing
- **THEN** validation SHALL fail with a message naming `input_sensors.grid_current_l2`

#### Scenario: Load references unknown device
- **WHEN** a `loads[]` entry references an EV charger ID that does not exist in `ev_chargers[]`
- **THEN** validation SHALL fail naming the offending entry

#### Scenario: Enabled with only a dynamically-throttled charger and no loads[]
- **WHEN** `load_balancing.enabled: true`, no `loads[]` entries exist, but one `ev_chargers[]` entry has `type: current`
- **THEN** validation SHALL pass (the charger satisfies the "at least one balanced load" requirement)

#### Scenario: loads[] references a type: current charger
- **WHEN** a `loads[]` entry's `device_id` matches an `ev_chargers[]` entry with `type: current`
- **THEN** validation SHALL fail, naming the charger and explaining it is already in the give-way list automatically and must not be listed in `loads[]`

#### Scenario: Sensor with unrecognized unit
- **WHEN** `input_sensors.grid_current_l1` points to an entity whose `unit_of_measurement` is not a recognized current or power unit
- **THEN** validation SHALL fail naming `input_sensors.grid_current_l1` and the unrecognized unit

#### Scenario: Enabled with a slow executor tick warns but does not block
- **WHEN** `load_balancing.enabled: true` and `executor.interval_seconds: 300`
- **THEN** validation SHALL emit a warning naming `executor.interval_seconds` and the ≤ 15 s recommendation
- **AND** startup SHALL proceed

#### Scenario: Current-type charger without a SoC sensor warns
- **WHEN** an `ev_chargers[]` entry has `type: current` and no `soc_sensor`
- **THEN** validation SHALL emit a warning naming that charger and the consequence for progress tracking
- **AND** startup SHALL proceed

### Requirement: Settings UI section
The frontend SHALL provide a load-balancing settings section with a global enable toggle, the fuse rating, per-phase sensor pickers (labeled to indicate either current or power sensors are accepted), anti-flap tuning fields, a nominal voltage field, a notifications toggle ("Notify on load balancer interventions", bound to `notify_interventions`), and a single reorderable **give-way list** replacing the previous two labeled groups:

- The list SHALL be ordered top-to-bottom, top gives way first, reorderable by drag with always-available up/down button fallback, and SHALL show no numeric priority fields.
- Every `type: current` EV charger SHALL appear in the list automatically (never user-added or user-removed); its row SHALL show name and configured phases read-only, a plain-language capability line derived from its configuration (e.g. "Throttle 16 → 6 A, then pause"), and a link to the EV tab where its settings live. Only its position SHALL be editable here.
- Shed loads (water heater, custom entity, `type: binary` EV charger) SHALL be addable/removable in the list, each with device, phases, and a capability line ("Switch off"). The EV charger picker for shed entries SHALL offer only `type: binary` chargers.
- The section copy SHALL state the top-down give-way rule in plain language and that phase assignment for on/off loads must match the physical installation.
- The reorderable-list control SHALL be implemented as a reusable component suitable for other ordered lists (e.g. a future excess-PV sink priority list).

When `load_balancing.enabled` is true and `executor.interval_seconds` exceeds 15, the section SHALL display a persistent inline warning naming both keys and the recommended tick. If any phase resolves to power-sensor mode, the settings UI SHALL show all three per-phase voltage entity fields together as one group (not conditionally per individual phase), each optional and independently falling back to the nominal voltage if left blank.

In the EV chargers settings tab, the current-control load type option SHALL be labeled "Dynamic" (config value unchanged), and while selected the UI SHALL display its consequences in plain language: the planner sets the charge current per slot, the charger is automatically included in the load-balancing give-way list (with a link to that tab), and it becomes eligible for future PV-surplus charging. When a `type: current` charger has no SoC sensor configured, the EV tab SHALL show an inline warning that Darkstar cannot track its charging progress.

#### Scenario: User enables the feature from the UI
- **WHEN** the user fills in fuse rating, sensors, and one give-way entry, then enables the toggle
- **THEN** the config SHALL be persisted through the existing config write path and validation feedback shown inline

#### Scenario: Power sensor reveals voltage fields
- **WHEN** the user selects a power-reporting entity for any of the three phase sensor fields
- **THEN** the settings UI SHALL show all three "Grid voltage sensor" fields together
- **AND** each SHALL be optional, independently

#### Scenario: User reorders a shed load above a charger
- **WHEN** the user drags the water heater entry above a charger entry and saves
- **THEN** `give_way_order` SHALL persist that order
- **AND** the balancer SHALL shed the water heater before throttling that charger (per `phase-load-balancing`)

#### Scenario: Charger rows are managed from the EV tab
- **WHEN** the user changes a charger's type from "Dynamic current (adjustable amps)" to "Binary (On/Off)" in the EV tab
- **THEN** the charger SHALL disappear from the give-way list's automatic entries
- **AND** it SHALL become offerable as a shed entry

#### Scenario: Choosing dynamic current explains its consequences
- **WHEN** the user selects "Dynamic current (adjustable amps)" for a charger in the EV tab
- **THEN** the UI SHALL display the consequence list (planner-controlled amps, automatic load balancing membership, PV-surplus eligibility) at the point of choice

#### Scenario: Slow tick shows a persistent warning in the section
- **WHEN** `load_balancing.enabled` is true and `executor.interval_seconds` is 60
- **THEN** the load-balancing settings section SHALL display an inline warning recommending ≤ 15 s

### Requirement: Live per-phase status
The system SHALL expose live balancer status — per-phase measured current, fuse rating, headroom, and the balancer's current action — via the existing live-metrics WebSocket emission and a REST status endpoint. The status SHALL include one named entry per dynamically-throttled EV charger (charger name, state — idle/throttling/paused/stale-fallback, current setpoint vs. planned target) rather than a single unnamed summary line, plus the shed-entry state (which loads are shed, with reason). The frontend SHALL render a status view with per-phase load bars against the fuse limit, a per-charger row for each dynamically-throttled charger, and the active shed state with its reason.

The status view SHALL additionally display a data-freshness indicator derived from the latest received payload's timestamp (e.g. "updated 3 s ago"), updating continuously, and SHALL visually flag staleness when the age materially exceeds the executor tick interval — so a system whose measured currents are legitimately near zero (e.g. a zero-export inverter covering the house load) remains distinguishable from a frozen or disconnected one.

#### Scenario: User watches the balancer act
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 is near the fuse limit
- **THEN** the status view SHALL show L1 near its limit and a row for that charger stating it's limited to 10 A (planned 16 A) because of L1

#### Scenario: Feature disabled
- **WHEN** `load_balancing.enabled` is false
- **THEN** the status view SHALL state the feature is disabled instead of showing empty bars

#### Scenario: Multiple dynamically-throttled chargers are individually visible
- **WHEN** two `type: current` EV chargers are configured and one is being throttled while the other charges at its planned target
- **THEN** the status view SHALL show two distinct named rows, one per charger, each reflecting its own state

#### Scenario: Quiet zero-export home still reads as live
- **WHEN** measured phase currents sit near 0 A for hours while the balancer runs normally
- **THEN** the freshness indicator SHALL keep showing a recent update age
- **AND** the view SHALL NOT be visually indistinguishable from a stalled data feed

#### Scenario: Stalled feed is flagged
- **WHEN** no live-metrics payload has arrived for materially longer than the executor tick interval
- **THEN** the status view SHALL visually flag the data as stale
