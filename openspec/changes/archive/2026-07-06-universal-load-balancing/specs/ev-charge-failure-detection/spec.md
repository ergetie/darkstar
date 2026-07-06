# Delta Spec: EV Charge Failure Detection

## MODIFIED Requirements

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
