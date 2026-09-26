## ADDED Requirements

### Requirement: Balancer can demand 1-phase mode for overload relief
The phase controller SHALL accept a relief demand from the load balancer (see `phase-load-balancing` "1-phase relief step in the degradation ladder"). When a relief demand is present and the charger is in 3-phase mode, the controller SHALL command 1-phase mode without waiting for the target-power threshold or hysteresis window. It SHALL still refuse the switch while `min_dwell_s` has not elapsed since the previous phase change, or while the controller is in its failed state. While the charger is in 1-phase mode because of a relief demand, the controller SHALL NOT return to 3-phase mode until both of these hold:
- (a) `min_dwell_s` has elapsed;
- (b) the balancer reports that every phase the charger would use in 3-phase mode has averaged headroom for `min_current_a` within `target_margin_percent`, sustained for the full `ramp_up_window_s`.

Once returned to 3-phase mode, the normal power-threshold state machine SHALL resume.

The same relief demand SHALL be used when the balancer re-fits a paused charger into 1-phase mode (see `phase-load-balancing` "Pause below minimum current with anti-flap resume"), with the same dwell and fail-safe rules. If the controller refuses the switch or the write fails, the charger SHALL stay paused rather than start in 3-phase mode.

#### Scenario: Relief overrides the power threshold
- **WHEN** the planner target is 6.9 kW (well above the 3-phase minimum) and the balancer demands relief
- **THEN** the controller SHALL command 1-phase mode, provided dwell has elapsed

#### Scenario: Relief-held 1-phase does not bounce back on target power alone
- **WHEN** the charger is in 1-phase mode due to relief, the planner target is above the 3-phase threshold, but L3's averaged current still leaves no room for 6 A within the target margin
- **THEN** the controller SHALL NOT command 3-phase mode

#### Scenario: Refused re-fit switch keeps the charger paused
- **WHEN** the balancer re-fits a paused charger into 1-phase mode and the phase-mode write fails
- **THEN** the charger SHALL stay paused and the confirm window SHALL start over

#### Scenario: Return to 3-phase after the load ends
- **WHEN** floor heating on L3 stops, all three phases have averaged room for 6 A within the target margin for 60 s, and 600 s have passed since the switch
- **THEN** the controller SHALL command 3-phase mode

### Requirement: Configurable 1-phase grid line
Each phase-switching charger SHALL declare `phase_1_line` (1, 2 or 3; default 1): the grid phase the charger draws on in 1-phase mode. The balancer SHALL use it to decide which phases a 1-phase switch relieves. While the charger is in 1-phase mode, the balancer SHALL attribute its draw only to that line. Validation SHALL reject a `phase_1_line` that is not among the charger's configured `phases`.

#### Scenario: Default line
- **WHEN** `phase_1_line` is absent
- **THEN** the charger SHALL be treated as drawing on L1 in 1-phase mode

#### Scenario: Charger wired to a different line
- **WHEN** `phase_1_line: 2` and L2 is overloaded
- **THEN** a 1-phase switch SHALL NOT be treated as relief for L2
