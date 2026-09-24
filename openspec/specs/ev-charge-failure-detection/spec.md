## Purpose

Detect when an EV charger silently fails to deliver scheduled power — for example, when a wallbox rejects a charge command — and surface the failure through the error notification path so it does not go unnoticed.

## Requirements

### Requirement: Executor detects EV charge failure when actual power stays zero

The executor SHALL track consecutive ticks where the executor's *commanded* EV charging level implies active charging (commanded switch ON for binary chargers, or a commanded ampere setpoint at or above the minimum current for current-type chargers) but actual EV power is below 0.1 kW. After 5 consecutive zero-power ticks under an active command, the executor SHALL raise an error through the existing "On Error" notification path and mark the execution record's success field as 0 (failed).

Failure detection SHALL compare against the commanded level, not the raw scheduled kW: when the load balancer has capped or paused charging, the reduced or zero command SHALL NOT be treated as a failure, and reduced actual power that matches a balancer-capped setpoint SHALL NOT be treated as a failure.

#### Scenario: EV wallbox rejects charge command

- **WHEN** the executor has commanded charging (switch ON or setpoint ≥ minimum current)
- **AND** actual EV power remains below 0.1 kW for 5 consecutive executor ticks
- **THEN** the executor sends an error notification via `dispatcher.notify_error()` with message including commanded and actual power
- **AND THEN** the execution record for that tick has `success = 0`

#### Scenario: EV charger ramps up within threshold

- **WHEN** the executor has commanded charging
- **AND** actual EV power exceeds 0.1 kW within 4 ticks
- **THEN** no error is raised
- **AND THEN** the zero-power tick counter resets to 0

#### Scenario: Balancer pause is not a failure

- **WHEN** the schedule has `ev_charging_kw = 10.0` for the current slot
- **AND** the load balancer has paused charging due to insufficient phase headroom
- **THEN** the zero-power tick counter SHALL NOT increment
- **AND** no failure notification is sent

#### Scenario: Balancer-throttled charging is not a failure

- **WHEN** the schedule plans 11 kW but the balancer caps the charger at 6 A (~4.1 kW)
- **AND** actual EV power is approximately 4 kW
- **THEN** no failure is detected

#### Scenario: Error fires only once per EV slot

- **WHEN** the EV charge failure error has already been sent for the current EV charging period
- **AND** actual EV power remains at 0 on subsequent ticks
- **THEN** no additional error notifications are sent

#### Scenario: Counter resets when EV slot ends

- **WHEN** the executor no longer commands charging (slot ended, or balancer/schedule stopped it)
- **THEN** the zero-power tick counter resets to 0
- **AND THEN** the failure-notified flag resets to false

### Requirement: Charge failure and recovery trigger a replan
When EV charge failure is first detected in an EV charging period, and again when actual EV power first exceeds 0.1 kW after a detected failure, the executor SHALL request an immediate replan. These requests SHALL use their own cooldown of 5 minutes between failure/recovery replans, independent of the balancer-replan rate limit (at most one balancer-triggered replan per planner interval); neither limit SHALL consume or block the other.

#### Scenario: Failure triggers replan
- **WHEN** charge failure is detected (5 consecutive zero-power ticks under an active command)
- **THEN** the executor SHALL request a replan in addition to the error notification

#### Scenario: Recovery triggers replan
- **WHEN** a failure was detected in this period and actual power then exceeds 0.1 kW
- **THEN** the executor SHALL request a replan so remaining time is re-planned

#### Scenario: Recovery shortly after failure
- **WHEN** a failure replan was requested at 10:16 and actual power exceeds 0.1 kW at 10:22
- **THEN** the executor SHALL request the recovery replan

#### Scenario: Cooldown
- **WHEN** a failure/recovery replan was requested less than 5 minutes ago
- **THEN** no further failure/recovery replan SHALL be requested until the cooldown has passed

#### Scenario: Recovery inside the cooldown is deferred, not dropped
- **WHEN** a failure replan was requested and actual power exceeds 0.1 kW less than 5 minutes later
- **THEN** the recovery replan SHALL stay pending
- **AND** SHALL be requested on the first tick with actual power above 0.1 kW after the cooldown has passed, unless the commanded period ends first

#### Scenario: Independent of balancer rate limit
- **WHEN** a balancer-triggered replan already ran within the current planner interval
- **THEN** a failure/recovery replan SHALL still be requested, and SHALL NOT consume the balancer's replan slot
