## ADDED Requirements

### Requirement: Measured EV draw per phase each tick
For every enabled `type: current` charger, the executor SHALL derive `measured_draw_a` (amps per phase) once per tick, before surplus feedback and load balancing run. Source order:
1. When per-phase sensors are configured and at least one is readable: the maximum reading across the charger's phases. A values are used as is; W/kW values are converted with 230 V.
2. Otherwise, when the charger's power `sensor` reading is healthy this tick: `power_w / (230 × active_phase_count)`.
3. Otherwise: no measurement (`None`).

#### Scenario: Total power sensor only
- **WHEN** a 3-phase charger has no per-phase sensors and its power sensor reads 6900 W
- **THEN** `measured_draw_a` SHALL be 10 A

#### Scenario: Per-phase sensors take precedence
- **WHEN** per-phase sensors read L1=9 A, L2=10 A, L3=9.5 A and the power sensor also reads a value
- **THEN** `measured_draw_a` SHALL be 10 A

#### Scenario: Sensor unavailable
- **WHEN** the power sensor is unavailable and no per-phase sensors are configured
- **THEN** `measured_draw_a` SHALL be `None`

### Requirement: Effective baseline for amps adjustments
The executor SHALL compute an effective baseline for a charging current-type charger as `max(min_current_a, min(commanded_setpoint_a, measured_draw_a))` when a measurement exists and the commanded setpoint has been unchanged for at least 30 s. Otherwise the effective baseline SHALL equal the commanded setpoint. A measurement above the setpoint SHALL never raise the baseline.

#### Scenario: Car draws less than the setpoint
- **WHEN** the setpoint is 16 A, unchanged for 60 s, and measured draw is 10 A
- **THEN** the effective baseline SHALL be 10 A

#### Scenario: Just after a setpoint change
- **WHEN** the setpoint changed to 6 A 10 s ago and measured draw is 0 A
- **THEN** the effective baseline SHALL be 6 A (the commanded setpoint)

#### Scenario: Measurement above setpoint
- **WHEN** the setpoint is 10 A and measured draw is 10.4 A
- **THEN** the effective baseline SHALL be 10 A

#### Scenario: No measurement
- **WHEN** `measured_draw_a` is `None`
- **THEN** the effective baseline SHALL equal the commanded setpoint
