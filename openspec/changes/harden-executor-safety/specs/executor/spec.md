## ADDED Requirements

### Requirement: Manual override does not write inverter settings

When the configured `manual_override_entity` is active (`state.manual_override_active` is true), the executor SHALL NOT write any inverter, EV-charger, or water-heater settings for that tick. This mirrors the pause short-circuit and honors the manual-override contract ("executor will not change settings"). State recording (execution history, slot observations) MAY still run so the UI reflects actual conditions.

#### Scenario: Manual override active skips inverter writes

- **WHEN** `state.manual_override_active` is true during a tick
- **THEN** the executor SHALL NOT push any battery mode, `soc_target`, charge/discharge, or export setting to the inverter
- **AND** the executor SHALL NOT write the EV charger switch or water heater setpoint

#### Scenario: Manual override inactive behaves normally

- **WHEN** `state.manual_override_active` is false
- **THEN** the executor SHALL evaluate and apply the plan as usual

#### Scenario: Manual override still records telemetry

- **WHEN** `state.manual_override_active` is true during a tick
- **THEN** execution-history and slot-observation recording SHALL still run for that tick

### Requirement: EV charger control obeys manual override and force_stop

EV charger switching SHALL consult manual-override and quick-action state, not only `ev_charger_plans`. Under manual override the executor SHALL NOT write the EV charger switch. Under the `force_stop` quick action the executor SHALL command the EV charger off, even if the slot plan schedules charging.

#### Scenario: force_stop stops a planned EV charge

- **WHEN** a `force_stop` quick action is active
- **AND** the current slot's `ev_charger_plans` schedules charging for a charger
- **THEN** the executor SHALL command that EV charger switch off

#### Scenario: Manual override leaves the EV charger untouched

- **WHEN** `state.manual_override_active` is true
- **THEN** the executor SHALL NOT write the EV charger switch state

#### Scenario: Normal operation follows the EV plan

- **WHEN** no manual override and no `force_stop` quick action are active
- **THEN** the executor SHALL control the EV charger per the slot's `ev_charger_plans`, as before

### Requirement: Executor rejects a stale schedule and holds

Before acting on the loaded schedule, the executor SHALL compare the schedule's generation time to the current time. If the schedule is older than `executor.max_schedule_age_hours` (optional config, default 6), the executor SHALL NOT execute it: it SHALL emit a warning via the existing system-alert path and fall back to the slot-failure hold behavior (`grid_charging=False`, `soc_target` = current SoC).

#### Scenario: Stale schedule triggers hold and alert

- **WHEN** the loaded schedule's generation time is older than `max_schedule_age_hours`
- **THEN** the executor SHALL emit a warning via the system-alert path
- **AND** the executor SHALL apply the hold fallback (`grid_charging=False`, `soc_target` = current SoC)
- **AND** the executor SHALL NOT apply the stale schedule's planned actions

#### Scenario: Fresh schedule executes normally

- **WHEN** the loaded schedule's generation time is within `max_schedule_age_hours`
- **THEN** the executor SHALL execute the schedule as planned

#### Scenario: Threshold is configurable with a default

- **WHEN** `executor.max_schedule_age_hours` is not set in config
- **THEN** the executor SHALL use a default of 6 hours for the freshness check
