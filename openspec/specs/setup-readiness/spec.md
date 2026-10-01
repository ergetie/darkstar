# setup-readiness Specification

## Purpose
Assess configuration readiness using live checks and a fresh isolated planner calculation without hardware actuation.

## Requirements

### Requirement: Readiness endpoint
The system SHALL provide `GET /api/setup/readiness` returning `ready` and a list of checks, each with `id`, `group`, `status` (`pass|warn|fail|skipped`), `message`, `fix_hint` and `settings_path`. `ready` SHALL be `true` only if no check has status `fail`.

#### Scenario: Fully configured system
- **WHEN** all applicable checks pass
- **THEN** `ready` SHALL be `true`

#### Scenario: One failing check
- **WHEN** `input_sensors.battery_soc` is empty and `has_battery` is true
- **THEN** a check in group `sensors` SHALL have status `fail` with a fix hint
- **AND** `ready` SHALL be `false`

### Requirement: Checks follow the system definition
Checks SHALL be selected by `system.has_solar`, `has_battery`, `has_water_heater`, `has_ev_charger` and `grid_meter_type`. Checks for disabled features SHALL have status `skipped`.

#### Scenario: No EV
- **WHEN** `has_ev_charger` is false
- **THEN** all EV checks SHALL be `skipped`

#### Scenario: Dual meter
- **WHEN** `grid_meter_type` is `dual`
- **THEN** `grid_import_power` and `grid_export_power` SHALL be checked and `grid_power` SHALL be skipped

### Requirement: Live sensor plausibility
For each required sensor the readiness check SHALL read the live HA state and fail when the entity is missing, `unavailable`, `unknown` or non-numeric, and warn when the unit or value is implausible for its role (e.g. SoC outside 0–100, power sensor without a W/kW unit).

#### Scenario: Unavailable sensor
- **WHEN** the configured `load_power` entity reports `unavailable`
- **THEN** its check SHALL be `fail`

#### Scenario: Wrong unit
- **WHEN** `pv_power` reports unit `kWh`
- **THEN** its check SHALL be `warn` with a hint that a power sensor is expected

### Requirement: Configuration and price checks
Readiness SHALL verify battery limits per planner preflight rules, PV arrays with kWp > 0, a location differing from the shipped placeholder, required profile entities existing in HA, water heater and EV entries passing save validation with existing entities, and a successful Nordpool fetch for the configured area.

#### Scenario: Placeholder location
- **WHEN** `system.location` equals the shipped default coordinates and `has_solar` is true
- **THEN** the location check SHALL be `fail`

#### Scenario: Missing battery power limits
- **WHEN** `has_battery` is true and `battery.max_charge_w` is 0
- **THEN** the battery check SHALL be `fail`

### Requirement: Non-actuating test plan
Readiness SHALL run a fresh isolated planner calculation and pass when a plan with at least one slot is produced. It SHALL NOT reuse a live planner result, publish a live schedule, invoke the executor, modify executor-facing planner state or write to any HA entity.

#### Scenario: Plan succeeds
- **WHEN** the planner run produces slots
- **THEN** the plan check SHALL be `pass` and report the slot count

#### Scenario: No hardware writes
- **WHEN** readiness runs in any executor mode
- **THEN** no HA service call SHALL be made

#### Scenario: Concurrent live planning
- **WHEN** a live scheduler plan is running while readiness is requested
- **THEN** readiness SHALL calculate its own fresh result without publishing a live schedule or involving the executor
