# Spec: Load Balancing Settings

## Purpose

Defines the configuration schema, startup validation, settings UI, and live status surface for the phase load balancing feature.

## Requirements

### Requirement: Load balancing configuration schema
The config SHALL support: `system.grid.main_fuse_a` (positive integer, per-phase fuse rating in ampere); `input_sensors.grid_current_l1/l2/l3` (HA entity IDs for per-phase grid current at the connection point); and a `load_balancing` section with `enabled` (bool, default false), `resume_delay_s` (default 120), `resume_margin_percent` (default 90), `increase_step_a` (default 1), `sensor_stale_after_s` (default 30), and `loads[]` (each entry: device reference to an EV charger, water heater, or custom entity; `phases` list; `priority` integer). `system.grid.max_power_kw` SHALL remain unchanged in meaning and use.

#### Scenario: Defaults are safe
- **WHEN** a user upgrades without touching config
- **THEN** `load_balancing.enabled` SHALL be false and no behavior changes

#### Scenario: Fuse rating is independent of planner budget
- **WHEN** `main_fuse_a: 20` and `max_power_kw: 8` are both set
- **THEN** the planner SHALL keep using 8 kW as its import budget while the balancer uses 20 A per phase

### Requirement: Startup validation with actionable errors
When `load_balancing.enabled` is true, startup validation SHALL verify that `main_fuse_a` is set and positive, all three per-phase sensors are configured, and `loads[]` contains at least one entry referencing an existing device with a non-empty `phases` list. Each violation SHALL produce an error naming the missing key and how to fix it. Implausible values (e.g. `main_fuse_a` > 125 or ≤ 0) SHALL be rejected.

#### Scenario: Enabled without phase sensors
- **WHEN** `load_balancing.enabled: true` but `grid_current_l2` is missing
- **THEN** validation SHALL fail with a message naming `input_sensors.grid_current_l2`

#### Scenario: Load references unknown device
- **WHEN** a `loads[]` entry references an EV charger ID that does not exist in `ev_chargers[]`
- **THEN** validation SHALL fail naming the offending entry

### Requirement: Settings UI section
The frontend SHALL provide a load-balancing settings section with a global enable toggle, the fuse rating, per-phase sensor pickers, anti-flap tuning fields, and an editable balanced-loads list (device, phases, priority). The section SHALL explain in plain language that phase assignment for on/off loads must match the physical installation.

#### Scenario: User enables the feature from the UI
- **WHEN** the user fills in fuse rating, sensors, and one load, then enables the toggle
- **THEN** the config SHALL be persisted through the existing config write path and validation feedback shown inline

### Requirement: Live per-phase status
The system SHALL expose live balancer status — per-phase measured current, fuse rating, headroom, and the balancer's current action (idle, throttling with setpoint vs. planned target, shedding which loads, paused with reason, stale-data fallback) — via the existing live-metrics WebSocket emission and a REST status endpoint. The frontend SHALL render a status view with per-phase load bars against the fuse limit and the active limitation with its reason.

#### Scenario: User watches the balancer act
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 is near the fuse limit
- **THEN** the status view SHALL show L1 near its limit and the message that the EV is limited to 10 A (planned 16 A) because of L1

#### Scenario: Feature disabled
- **WHEN** `load_balancing.enabled` is false
- **THEN** the status view SHALL state the feature is disabled instead of showing empty bars
