## ADDED Requirements

### Requirement: Every EV action is recorded in the execution log
The executor SHALL write an execution record for every EV dispatch result (switch enable/disable, current setpoint, stop, phase-mode change), whether it succeeded or failed. Each record SHALL use `source="ev_charger"` and a `commanded_work_mode` of `ev_charge_start`, `ev_charge_stop`, `ev_charge_current` or `ev_phase_mode`, and SHALL set `success` from the result. On failure, `error_message` SHALL carry the error details. `action_results` SHALL include `charger_id`, `entity_id`, `previous_value` and the `new_value` actually sent (amps or option). Results skipped because the entity was already at the target SHALL NOT be recorded.

#### Scenario: Failed current write is recorded
- **WHEN** writing 6 A to a charger's current entity fails with HA HTTP 500
- **THEN** an execution record SHALL exist with `source="ev_charger"`, `success=0`, `new_value=6` and the HTTP error in `error_message`

#### Scenario: Failed switch write is recorded
- **WHEN** setting the charger's switch to `charge` fails
- **THEN** an execution record SHALL exist with `success=0`, `commanded_work_mode="ev_charge_start"` and the error details

#### Scenario: Phase mode change is recorded
- **WHEN** the executor switches a charger's phase mode
- **THEN** a dedicated `ev_phase_mode` execution record SHALL be written

### Requirement: Repeated identical EV failures are deduplicated
Within 5 minutes, a consecutive identical failure (same charger, action, value and error) SHALL NOT produce another execution record. The number of suppressed repeats SHALL be included in the next record written for that charger and action.

#### Scenario: Same failure every tick
- **WHEN** the same current write fails on 10 consecutive attempts within 5 minutes
- **THEN** exactly one failure record SHALL be written in that window
- **AND** the next record for that charger/action SHALL state the repeat count

### Requirement: Per-charger EV write failure backoff
After a failed EV write, the executor SHALL skip further writes to that charger for `min(60 s × 2^(n−1), 600 s)`, where n is the number of consecutive failures. The backoff SHALL reset on a successful write or when the charger's desired state changes. While a charger is in backoff, the tick SHALL NOT wait on HA retries for it.

#### Scenario: Failing charger does not stall ticks
- **WHEN** a charger's write failed on the previous tick and its backoff has not expired
- **THEN** the next tick SHALL make no HA call for that charger

#### Scenario: Desired state change resets backoff
- **WHEN** a charger is in backoff and the plan changes from charging to stop
- **THEN** the executor SHALL attempt the stop write immediately

### Requirement: EV failure logs include the attempted value
Logger output for a failed EV write SHALL include the charger id, the entity and the value attempted. Failure messages SHALL NOT use success wording.

#### Scenario: Current write fails
- **WHEN** writing 6 A fails
- **THEN** the log line SHALL contain the entity id, `6` A and the error

### Requirement: Execution history can be filtered by source
`GET /api/executor/history` SHALL accept an optional `source` parameter (`native` or `ev_charger`) and return only matching records. The CSV export SHALL respect the same filter. The Executor page SHALL offer a source filter (All / Inverter / EV) and SHALL show a distinct badge for each EV work mode, with the charger id, value sent and error shown in the record details.

#### Scenario: Filter to EV actions
- **WHEN** the user selects "EV" in the Executor history filter
- **THEN** only records with `source="ev_charger"` SHALL be listed, each with an EV badge
