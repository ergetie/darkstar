## ADDED Requirements

### Requirement: Executor holds plug state for a grace window while unreachable
While a charger's plug sensor is unreachable, the executor SHALL use the last known valid plug reading for up to the charger's `plug_unreachable_grace_minutes` (default 10), and treat the plug as unknown afterwards or if never seen. The planner and dashboard SHALL keep the last known state for the whole outage.

#### Scenario: Short outage while charging
- **WHEN** the plug sensor is unavailable for 3.5 minutes with the last known state plugged and the window is 10 minutes
- **THEN** the executor SHALL keep the planned EV kW for the slot

#### Scenario: Outage past the window
- **WHEN** the plug sensor has been unavailable for 11 minutes with a 10 minute window
- **THEN** the effective plug state SHALL be unknown and planned EV kW SHALL be dropped

#### Scenario: Planner unaffected
- **WHEN** the outage lasts 30 minutes
- **THEN** the planner SHALL still plan with the last known plug state and `unreachable=true`

#### Scenario: Never seen
- **WHEN** the plug sensor is unavailable and no valid reading was ever recorded
- **THEN** the plug state SHALL be unknown

#### Scenario: Last known unplugged
- **WHEN** the sensor is unavailable within the window and the last known state was unplugged
- **THEN** the effective state SHALL be unplugged

### Requirement: Reconnect re-plan only after a long outage
When a charger becomes reachable again with an unchanged plugged state, the WebSocket handler SHALL request a re-plan only if the outage lasted at least the grace window. A changed plug state SHALL always follow the existing plug-in/unplug re-plan rules.

#### Scenario: Short reconnect
- **WHEN** the charger returns after 3.5 minutes still plugged
- **THEN** no re-plan SHALL be requested and the current slot's charging SHALL continue

#### Scenario: Long outage
- **WHEN** the charger returns after 25 minutes still plugged
- **THEN** an immediate re-plan SHALL be requested for that charger

### Requirement: Load balancer fail-safes unchanged
The grace window SHALL NOT apply to grid phase-current sensors; their stale-sensor fail-safes are unchanged.

#### Scenario: Phase sensor unavailable
- **WHEN** a grid phase-current sensor is stale during a plug-sensor grace window
- **THEN** the load balancer SHALL apply its existing fail-safe
