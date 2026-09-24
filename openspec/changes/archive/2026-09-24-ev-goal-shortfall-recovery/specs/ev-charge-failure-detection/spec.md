## ADDED Requirements

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
