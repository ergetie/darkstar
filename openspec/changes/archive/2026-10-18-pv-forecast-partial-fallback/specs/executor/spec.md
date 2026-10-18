## MODIFIED Requirements

### Requirement: Executor rejects a stale schedule and holds

Before acting on the loaded schedule, the executor SHALL compare the schedule's generation time to the current time. If the schedule is older than `executor.max_schedule_age_hours` (optional config, default 2), the executor SHALL NOT execute it: it SHALL emit a warning via the existing system-alert path and fall back to the slot-failure hold behavior (`grid_charging=False`, `soc_target` = current SoC).

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
- **THEN** the executor SHALL use a default of 2 hours for the freshness check
