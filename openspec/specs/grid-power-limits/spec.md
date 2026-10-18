# Capability: Grid Power Limits

## Purpose

Provides UI configuration for grid fuse hard limit (`system.grid.max_power_kw`), ensuring the planner never schedules power imports that exceed the physical grid connection capacity.

## Requirements

### Requirement: Grid Max Power Configuration UI

The system SHALL expose `system.grid.max_power_kw` in the Settings UI System tab, allowing users to configure their grid fuse hard limit.

#### Scenario: User configures grid max power
- **WHEN** user navigates to Settings > System tab
- **THEN** a "Grid Max Power (kW)" field is visible with helper text "HARD limit from your grid fuse. The planner will never exceed this."
- **AND** the field saves to `system.grid.max_power_kw` in config.yaml

#### Scenario: Planner respects grid max power limit
- **WHEN** planner generates a schedule
- **THEN** scheduled grid import SHALL NOT exceed `system.grid.max_power_kw`
- **AND** `max_import_power_kw` in KeplerConfig is set to this value

### Requirement: PV Dump Threshold Field Visible

The system SHALL display `executor.override.excess_pv_threshold_kw` in the Settings Water tab when both solar and water heater are enabled.

#### Scenario: PV dump threshold visible when conditions met
- **WHEN** user has `system.has_solar = true` AND `system.has_water_heater = true`
- **AND** user navigates to Settings > Water tab > Temperatures section
- **THEN** "PV Dump Threshold (kW)" field is visible
- **AND** helper text explains "Surplus PV power required to trigger water heating"

#### Scenario: PV dump threshold hidden when conditions not met
- **WHEN** user has `system.has_solar = false` OR `system.has_water_heater = false`
- **THEN** "PV Dump Threshold (kW)" field is NOT visible

### Requirement: Planner bounds EV phase load by the main fuse

When `system.grid.main_fuse_a` is set and positive, the planner SHALL constrain every slot in which a phase-limited charger can draw, so that the load on each grid phase carrying a plugged-in `type: current` EV charger with fewer than 3 configured `phases` does not exceed `main_fuse_a x load_balancing.target_margin_percent / 100 x system.grid.nominal_voltage_v` (margin default 85%, same as the runtime load balancer).

#### Scenario: Single-phase EV does not stack with battery grid charging
- **GIVEN** a 1-phase EV charger on L1 (max 16 A), `main_fuse_a` 20, 230 V and `target_margin_percent` 85, and a cheap-price window where battery grid charging and EV charging are both attractive
- **WHEN** the planner solves the window
- **THEN** in every slot where the EV can draw, EV kW + (net grid import kW - EV kW) / 3 SHALL be at most 3.91 kW

### Requirement: EV phase constraint load model and scope of slots

The planner SHALL treat the EV's power as spread evenly over its configured phases, and non-EV load (battery grid charge, water heating, house load) as spread evenly over the three phases and otherwise governed by the existing total grid cap. The constraint SHALL apply only to slots where such a charger can draw (plugged in and available), and SHALL be in addition to `system.grid.max_power_kw`.

#### Scenario: Constraint never makes the plan infeasible
- **WHEN** house load alone in a slot exceeds the limit
- **THEN** the solver SHALL still return a plan, reducing EV charging first and using the existing load-shedding slack for any remainder, as it does for `max_power_kw`

### Requirement: EV phase constraint exclusions

The EV phase constraint SHALL NOT apply to 3-phase chargers, `type: binary` chargers, or when `main_fuse_a` is unset.

#### Scenario: Three-phase EV unchanged
- **WHEN** the EV charger is configured with phases `[1, 2, 3]`
- **THEN** the plan SHALL be identical to the plan without the constraint

#### Scenario: Fuse unset
- **WHEN** `system.grid.main_fuse_a` is not set
- **THEN** the plan SHALL be identical to the plan without the constraint
