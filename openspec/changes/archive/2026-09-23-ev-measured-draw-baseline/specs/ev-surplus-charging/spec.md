## MODIFIED Requirements

### Requirement: Executor tracks measured surplus in real time during surplus-eligible slots

During a slot marked surplus-eligible for a charger, the executor SHALL each tick derive the live surplus from `SystemState` (export power for dual grid meters; negative grid power for net meters) and adjust the charger's ampere setpoint by feedback: raise the setpoint (subject to the increase-slow ramp from load balancing) while export exceeds a configurable deadband (default 0.2 kW), and lower it immediately while import exceeds the deadband. Both adjustments SHALL be computed from the charger's effective baseline (see `ev-measured-draw`), not from the last commanded setpoint, so that a reduction always lands below what the car is actually drawing. The planner's `ev_surplus_kw` value SHALL be treated as eligibility, not as an open-loop target.

#### Scenario: Setpoint rises while exporting
- **WHEN** the slot is surplus-eligible and measured export is 2.5 kW with a 0.2 kW deadband
- **THEN** the executor SHALL raise the EV ampere setpoint toward absorbing the export, honoring the ramp-rate limit

#### Scenario: Setpoint drops when a cloud removes the surplus
- **WHEN** the EV is surplus-charging and measured grid import rises to 1.5 kW
- **THEN** the executor SHALL lower the ampere setpoint on the same tick without ramp-rate limitation

#### Scenario: Reduction acts on actual draw
- **WHEN** a 3-phase EV has a settled 16 A setpoint, measures 10 A draw, and grid import is 2.07 kW with a 0.2 kW deadband
- **THEN** the new setpoint SHALL be 7 A (10 A − 3 A), not 13 A

#### Scenario: Stable within deadband
- **WHEN** measured grid exchange is within ±0.2 kW of zero
- **THEN** the executor SHALL keep the current setpoint unchanged

#### Scenario: Non-eligible slots behave as scheduled charging
- **WHEN** the current slot has no `ev_surplus_kw` entry for the charger
- **THEN** EV control SHALL follow the normal scheduled-charging behavior with no surplus feedback
