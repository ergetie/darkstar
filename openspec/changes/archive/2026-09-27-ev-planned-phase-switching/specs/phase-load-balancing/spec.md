## ADDED Requirements

### Requirement: Ramp-up hold-off after a setpoint reduction

After the balancer reduces an EV charger's setpoint for any reason (throttle, floor degrade, 1-phase relief), it SHALL NOT increase that charger's setpoint until `ramp_up_window_s` has passed since the reduction. Reductions SHALL NOT be delayed by the hold-off. The hold-off SHALL be cleared when the charger's plan ends or it is paused.

#### Scenario: New house load does not cause a sawtooth
- **WHEN** a water heater starts on L3 and the balancer reduces the charger from 10 A to 8 A at 12:39:20
- **AND** the 60 s average of L3 still leaves room because it contains samples from before the load started
- **THEN** the balancer SHALL NOT raise the setpoint before 12:40:20

#### Scenario: Ramp resumes after the hold-off
- **WHEN** 60 s have passed since the last reduction and the averaged current plus the increase stays within the target margin
- **THEN** the balancer SHALL raise the setpoint by at most `increase_step_a` per tick

#### Scenario: A further reduction restarts the hold-off
- **WHEN** the balancer reduces the setpoint again during the hold-off
- **THEN** the hold-off SHALL restart from the new reduction

#### Scenario: Reductions are never held
- **WHEN** a phase exceeds `main_fuse_a` during the hold-off
- **THEN** the balancer SHALL reduce the setpoint in the same tick
