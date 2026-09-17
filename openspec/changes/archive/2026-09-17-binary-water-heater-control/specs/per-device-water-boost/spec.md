## ADDED Requirements

### Requirement: Manual boost targets specific water heaters

The manual water boost API SHALL accept the water heater or heaters to boost. When the caller names no heater, the system SHALL boost every enabled heater that has a control entity configured, preserving the behavior expected by existing single-heater callers.

#### Scenario: Boost a named heater
- **GIVEN** heaters `main_tank` and `upstairs_tank` are configured
- **WHEN** a boost is requested for `upstairs_tank`
- **THEN** `upstairs_tank` SHALL be boosted
- **AND** `main_tank` SHALL continue to follow its schedule

#### Scenario: Boost with no heater named
- **GIVEN** two enabled heaters with control entities
- **WHEN** a boost is requested without naming a heater
- **THEN** both heaters SHALL be boosted

#### Scenario: Boost naming an unknown heater
- **WHEN** a boost is requested for a heater id that is not configured
- **THEN** the request SHALL be rejected with an error identifying the unknown heater
- **AND** no heater SHALL be boosted

### Requirement: Boost state is tracked per heater

The executor SHALL hold a boost deadline per heater id rather than a single global deadline, so heaters can be boosted, expire, and be cleared independently.

#### Scenario: Independent expiry
- **GIVEN** `main_tank` is boosted for 30 minutes and `upstairs_tank` for 60 minutes
- **WHEN** 45 minutes have passed
- **THEN** `main_tank` SHALL no longer be boosted
- **AND** `upstairs_tank` SHALL still be boosted

#### Scenario: Clearing one heater's boost
- **GIVEN** two heaters are boosted
- **WHEN** the boost is cleared for one of them
- **THEN** only that heater SHALL stop being boosted
- **AND** the other SHALL remain boosted until its own deadline

#### Scenario: Boost status reports per heater
- **WHEN** boost status is requested
- **THEN** the response SHALL identify which heaters are boosted and when each boost expires

### Requirement: Manual boost reaches the heater through the per-device control loop

An active manual boost SHALL be applied by populating the boosted heater's entry in the controller decision's per-device water temperatures, so the boost is dispatched by the same per-device control loop that executes the schedule. The executor SHALL NOT depend on the legacy single-heater target entity to deliver a manual boost.

#### Scenario: Boost is written to the heater's own entity
- **GIVEN** a temperature-controlled heater `main_tank` with its own control entity
- **AND** no legacy single-heater target entity is configured
- **WHEN** a manual boost is active for `main_tank`
- **AND** the executor tick executes
- **THEN** `temp_boost` SHALL be written to `main_tank`'s control entity

#### Scenario: Boost on a binary heater switches it on
- **GIVEN** a binary heater with a switch control entity
- **WHEN** a manual boost is active for that heater
- **AND** the executor tick executes
- **THEN** that heater SHALL be switched ON
- **AND** no temperature value SHALL be written for it

#### Scenario: Non-boosted heaters are unaffected
- **GIVEN** heaters `main_tank` and `upstairs_tank`
- **AND** a manual boost is active only for `main_tank`
- **WHEN** the executor tick executes
- **THEN** `upstairs_tank` SHALL be controlled according to the schedule, not the boost

#### Scenario: Boost ends and the schedule resumes
- **GIVEN** a heater whose manual boost has just expired or been cleared
- **WHEN** the next executor tick executes
- **THEN** that heater SHALL be controlled according to the current schedule

### Requirement: Boost precedence and battery protection are preserved

Battery state-of-charge protection SHALL continue to cancel an active boost, and a load-balancer shed SHALL continue to take precedence over a boost. Both SHALL apply per heater.

#### Scenario: Low battery cancels boost
- **GIVEN** a manual boost is active
- **WHEN** state of charge falls below the configured boost floor
- **THEN** the boost SHALL be cancelled
- **AND** the cancellation notification SHALL be delivered

#### Scenario: Shed overrides boost for the shed heater
- **GIVEN** heater `main_tank` is boosted
- **AND** the load balancer selects `main_tank` to shed
- **WHEN** the executor tick executes
- **THEN** `main_tank` SHALL be turned off or set to `temp_off` according to its control type
- **AND** any other boosted heater that was not shed SHALL remain boosted

### Requirement: Boost UI reflects per-device boost

The user interface SHALL let the user choose which heater to boost when more than one is configured, and SHALL show which heaters are currently boosted. When only one heater is configured, boosting SHALL remain a single action with no selection step.

#### Scenario: Selection offered with multiple heaters
- **GIVEN** two water heaters are configured
- **WHEN** the user opens the boost control
- **THEN** the user SHALL be able to choose which heater to boost

#### Scenario: No selection with a single heater
- **GIVEN** exactly one water heater is configured
- **WHEN** the user opens the boost control
- **THEN** boosting SHALL require no heater selection

#### Scenario: Active boosts are visible
- **GIVEN** one of two heaters is boosted
- **WHEN** the dashboard boost indicator is rendered
- **THEN** it SHALL show which heater is boosted and its remaining time
