## MODIFIED Requirements

### Requirement: Load balancing configuration schema
The config SHALL support: `system.grid.main_fuse_a` (positive integer, per-phase fuse rating in ampere); `input_sensors.grid_current_l1/l2/l3` (HA entity IDs for per-phase current or power through the protected fuse — the value SHALL be auto-detected as a current or power sensor per the `phase-load-balancing` capability). The key naming, voltage sensors, the `load_balancing` section keys, `loads[]` and `give_way_order[]` are specified in the scenarios below.

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

#### Scenario: Explicit participation survives config load
- **WHEN** the config is loaded
- **THEN** `give_way_order` SHALL retain only valid selected entries when `auto_include_devices` is false; missing devices SHALL NOT be added, and an empty list SHALL remain empty
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

#### Scenario: New chargers require selection
- **WHEN** a new `type: current` charger is added to `ev_chargers[]` without touching `give_way_order`
- **THEN** it SHALL remain outside balancing until selected in the give-way editor when `auto_include_devices` is false

#### Scenario: Charger switched back to binary drops out of the order
- **WHEN** a charger referenced in `give_way_order` is changed to `type: binary`
- **THEN** the next config load SHALL drop that entry with a logged warning

### Requirement: Startup validation with actionable errors
When load balancing is enabled, validation SHALL require a positive effective protected-fuse rating and three configured phase sensors. Selected entries SHALL reference valid devices. An explicit empty give-way list SHALL be allowed and leave balancing inactive while normal scheduling continues. Errors SHALL name the relevant key and fix.

#### Scenario: Implausible fuse values rejected
- **WHEN** `main_fuse_a` is greater than 125 or less than or equal to 0
- **THEN** startup validation SHALL reject the value

#### Scenario: Sensor unit validation
- **WHEN** startup validation checks each configured per-phase sensor
- **THEN** validation SHALL confirm its unit resolves to a recognized current or power unit
- **AND** an unrecognized unit SHALL fail validation naming the phase and the offending entity
- **AND** if any phase resolves to power-sensor mode, `load_balancing.nominal_voltage_v` (or that phase's voltage entity) SHALL be available; since `nominal_voltage_v` always has a default, this SHALL never block validation on its own

#### Scenario: Current-type charger in loads[] fails validation
- **WHEN** a `loads[]` entry references an EV charger whose `type` is `current`
- **THEN** validation SHALL fail with a message directing the user to the give-way list instead (the charger can be selected there)

#### Scenario: Non-blocking validation warnings
- **WHEN** validation runs
- **THEN** it SHALL additionally emit non-blocking warnings (logged and surfaced in the settings UI, never failing startup)
- **AND** when `load_balancing.enabled` is true and `executor.interval_seconds` exceeds 15, a warning SHALL name both keys and state that the balancer reacts and reports only once per tick (recommended ≤ 15 s)
- **AND** when any `type: current` EV charger has no `soc_sensor` configured, a warning SHALL name the charger and state that Darkstar cannot track its charging progress or recover throttling shortfall (plan-time SoC is assumed 0%)

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
- **THEN** validation SHALL fail, naming the charger and explaining it belongs in the give-way list as a selectable charger entry and must not be listed in `loads[]`

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
The frontend SHALL provide a load-balancing settings section with a global enable toggle, the fuse rating, per-phase sensor pickers (labeled to indicate either current or power sensors are accepted), anti-flap tuning fields, a nominal voltage field, a notifications toggle ("Notify on load balancer interventions", bound to `notify_interventions`), and a single reorderable **give-way list** replacing the previous two labeled groups, with the behavior specified in the scenarios below.

#### Scenario: Give-way list behavior and content
- **WHEN** the give-way list is displayed
- **THEN** the list SHALL be ordered top-to-bottom, top gives way first, reorderable by drag with always-available up/down button fallback, and SHALL show no numeric priority fields
- **AND** the reorderable-list control SHALL be implemented as a reusable component suitable for other ordered lists (e.g. a future excess-PV sink priority list)
- **AND** the section copy SHALL state the top-down give-way rule in plain language and that phase assignment for on/off loads must match the physical installation

#### Scenario: Current-type chargers in the give-way list
- **WHEN** a `type: current` EV charger exists
- **THEN** it SHALL be available to add to the list and remove without deleting its charger configuration
- **AND** its row SHALL show name and configured phases read-only, a plain-language capability line derived from its configuration (e.g. "Throttle 16 → 6 A, then pause"), and a link to the EV tab where its settings live
- **AND** only its position SHALL be editable here

#### Scenario: Shed loads in the give-way list
- **WHEN** the user manages shed loads (water heater, custom entity, `type: binary` EV charger)
- **THEN** they SHALL be addable/removable in the list, each with device, phases, and a capability line ("Switch off")
- **AND** the EV charger picker for shed entries SHALL offer only `type: binary` chargers

#### Scenario: Settings tab always visible
- **WHEN** navigation is rendered
- **THEN** the settings tab SHALL always be visible, regardless of `system.has_ev_charger` or `system.has_water_heater`
- **AND** it SHALL NOT be conditionally hidden the way hardware-specific tabs (Solar, Battery, EV, Heating) are, since a `custom_entity` shed load requires no system flag at all

#### Scenario: Empty give-way list message
- **WHEN** the give-way list is empty (no `type: current` EV charger auto-included and no `loads[]` entries configured, regardless of the `has_ev_charger`/`has_water_heater` flags)
- **THEN** the give-way section SHALL display an inline explanatory message pointing to the ways to populate it (a dynamically-throttled EV charger configured in the EV tab, or a water heater/custom entity added directly here) instead of a bare empty list
- **AND** this message SHALL NOT block use of the enable toggle, fuse rating, or sensor fields

#### Scenario: Tick interval warning and voltage field group
- **WHEN** `load_balancing.enabled` is true and `executor.interval_seconds` exceeds 15
- **THEN** the section SHALL display a persistent inline warning naming both keys and the recommended tick
- **WHEN** any phase resolves to power-sensor mode
- **THEN** the settings UI SHALL show all three per-phase voltage entity fields together as one group (not conditionally per individual phase), each optional and independently falling back to the nominal voltage if left blank

#### Scenario: EV tab Dynamic load type
- **WHEN** the EV chargers settings tab shows the current-control load type option
- **THEN** it SHALL be labeled "Dynamic" (config value unchanged)
- **AND** while selected, the UI SHALL display its consequences in plain language: the planner sets the charge current per slot, the charger can be selected in the load-balancing give-way list (with a link to that tab), and it becomes eligible for future PV-surplus charging
- **AND** when a `type: current` charger has no SoC sensor configured, the EV tab SHALL show an inline warning that Darkstar cannot track its charging progress

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
- **THEN** the charger SHALL disappear from the give-way list's available charger entries
- **AND** it SHALL become offerable as a shed entry

#### Scenario: Choosing dynamic current explains its consequences
- **WHEN** the user selects "Dynamic current (adjustable amps)" for a charger in the EV tab
- **THEN** the UI SHALL display the consequence list (planner-controlled amps, optional load balancing membership, PV-surplus eligibility) at the point of choice

#### Scenario: Slow tick shows a persistent warning in the section
- **WHEN** `load_balancing.enabled` is true and `executor.interval_seconds` is 60
- **THEN** the load-balancing settings section SHALL display an inline warning recommending ≤ 15 s

#### Scenario: Tab visible with no EV charger and no water heater
- **WHEN** `system.has_ev_charger` is false and `system.has_water_heater` is false
- **THEN** the Load Balancing settings tab SHALL still appear in navigation

#### Scenario: Empty state explains prerequisites
- **WHEN** the give-way list has no `type: current` EV charger and `load_balancing.loads[]` is empty (regardless of `system.has_water_heater`/`system.has_ev_charger`)
- **THEN** the section SHALL display a message explaining the give-way list can be populated by a dynamic EV charger, a water heater, or a custom entity added here
- **AND** the enable toggle, fuse rating, and sensor fields SHALL remain usable

#### Scenario: Give-way list populated by a custom entity alone
- **WHEN** the system has no EV charger and no water heater, but the user adds a `custom_entity` shed load to `load_balancing.loads[]`
- **THEN** the empty-state message SHALL NOT be shown
- **AND** the give-way list SHALL show that entry

### Requirement: Graceful degradation settings
The `load_balancing` config section SHALL additionally support the graceful-degradation keys, validation, migration and settings exposure specified in the scenarios below.

#### Scenario: Graceful degradation config keys
- **WHEN** the `load_balancing` config section is read
- **THEN** it SHALL support `target_margin_percent`: number, default 85, valid range 50–100
- **AND** `resume_confirm_s`: integer, default 10, valid range 5–300, which is how long a balancer-paused charger's phases must fit before it re-fits (see `phase-load-balancing` "Pause below minimum current with anti-flap resume")
- **AND** `ramp_up_window_s`: integer, default 60, valid range 10–600, used only as the averaging window for increases and restores (not as a hold-off)
- **AND** `fuse_preset`, `fuse_safety_percent` and `fuse_custom_points` as specified in `fuse-overload-timing` "Fuse configuration keys"
- **AND** `pause_debounce_s` and `severe_overload_percent` are no longer supported

#### Scenario: phase_1_line and range validation
- **WHEN** an `ev_chargers[]` entry or one of the new keys is validated
- **THEN** each `ev_chargers[]` entry SHALL additionally support `phase_1_line` (1, 2 or 3; default 1)
- **AND** out-of-range values SHALL fail validation with an error naming the key and its valid range

#### Scenario: target_margin_percent supersedes resume_margin_percent
- **WHEN** the config is loaded
- **THEN** `target_margin_percent` supersedes `resume_margin_percent`
- **AND** a user-tuned `resume_margin_percent` with no `target_margin_percent` SHALL be migrated to `target_margin_percent` with the same value, and the old key dropped
- **AND** a `resume_margin_percent` still at its old shipped default (90) carries no user intent (the template merge wrote it into every config) and SHALL be dropped so the new, more protective default applies
- **AND** when both keys exist, `target_margin_percent` wins
- **AND** this migration SHALL be idempotent and logged
- **AND** `config.default.yaml` SHALL ship the new keys with explanatory comments

#### Scenario: resume_delay_s scope
- **WHEN** a balancer-paused charger is resumed
- **THEN** `resume_delay_s` keeps its key and default (120 s) but no longer gates resuming a balancer-paused charger
- **AND** it SHALL continue to govern restoring shed loads, the stale-sensor escalation from minimum-current fallback to pause, and the EV surplus controller's resume; its help text SHALL say so
- **AND** no migration is needed: `resume_confirm_s` is added by the template merge with its default

#### Scenario: Settings section exposes global fields
- **WHEN** the load-balancing settings section is displayed
- **THEN** it SHALL expose the global fields, with plain-language help, e.g. "Aim to keep each phase at or below this share of your fuse" and "A paused charger starts again once its phases have had room for the minimum current for this long"
- **AND** it SHALL expose `phase_1_line`, shown in the EV charger's phase-switching block only when phase switching is enabled

#### Scenario: Upgrade picks safe defaults
- **WHEN** a user with load balancing enabled upgrades without touching config
- **THEN** the balancer SHALL use an 85 % target, 10 s resume confirm time, the Typ C fuse curve with 80 % safety and a 60 s ramp-up averaging window

#### Scenario: Tuned legacy resume margin is migrated
- **WHEN** a config has `resume_margin_percent: 80` and no `target_margin_percent`
- **THEN** after load, `target_margin_percent` SHALL be 80 and `resume_margin_percent` SHALL be absent

#### Scenario: Untouched legacy default takes the new default
- **WHEN** a config has `resume_margin_percent: 90` (the old default) and no `target_margin_percent`
- **THEN** after load, `resume_margin_percent` SHALL be absent and the balancer SHALL use the 85 % default

#### Scenario: Invalid debounce is rejected
- **WHEN** a config contains `pause_debounce_s: 120` or `severe_overload_percent: 300`
- **THEN** it SHALL load without a validation error and the keys SHALL be removed by the deprecated-key sweep (see `config-migration` "Remove balancer pause-delay and severe-overload settings")


#### Scenario: Invalid resume confirm time is rejected
- **WHEN** a user saves `resume_confirm_s: 2`
- **THEN** validation SHALL fail naming `load_balancing.resume_confirm_s` and its 5–300 range

### Requirement: Battery entry self-heal
`heal_give_way_order` SHALL keep a battery entry only while a controllable battery exists, meaning a loaded inverter profile with a `charge` mode. Otherwise it SHALL drop the entry with a warning. Only legacy automatic inclusion SHALL append a missing battery entry. With `auto_include_devices: false`, the battery SHALL remain absent until selected; frontend display healing SHALL never reinsert it.

#### Scenario: Existing user upgrades
- **WHEN** a legacy config without `auto_include_devices` is loaded and a Deye profile is active
- **THEN** migration SHALL append the previously automatic battery entry after the last entry once and set `auto_include_devices: false`

#### Scenario: No inverter profile
- **WHEN** no inverter profile is loaded
- **THEN** any battery entry SHALL be dropped from the effective order

## ADDED Requirements

### Requirement: Explicit protected-fuse participation
The give-way list SHALL select which devices participate in protecting the configured fuse. Settings and dashboard SHALL use “Protected fuse” and neutral phase-sensor labels. Configuration key names SHALL remain backward compatible. `auto_include_devices: false` SHALL make the order authoritative, including an empty list.

#### Scenario: Existing participation preserved on upgrade
- **WHEN** an existing installation lacks the explicit-participation setting
- **THEN** migration SHALL materialize its legacy effective order and set `auto_include_devices` false once, without changing the previous participating devices
- **AND** config GET SHALL provide the same effective view without writing to disk if migration has not completed

#### Scenario: Optional charger and battery membership
- **WHEN** a user removes or re-adds a charger or battery grid-charging entry
- **THEN** only the selected valid entries SHALL participate after save, reload and restart
- **AND** removing an entry SHALL preserve its normal scheduling and clear any previous balancing restriction

#### Scenario: Explain the physical boundary briefly
- **WHEN** a user configures give-way loads
- **THEN** the UI SHALL state “Only include loads whose reduction lowers current through the protected fuse.”
- **AND** further explanation SHALL be in a collapsed disclosure

#### Scenario: Protected rating independent of grid planning
- **WHEN** `load_balancing.protected_fuse_a` differs from `system.grid.main_fuse_a`
- **THEN** the balancer SHALL use the protected rating while the planner retains the grid connection rating
- **AND** old configs without a protected rating SHALL keep the previous grid-rating fallback
- **AND** settings SHALL expose both values under their respective protected-fuse and grid-planning labels
