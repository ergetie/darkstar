## MODIFIED Requirements

### Requirement: 1-phase relief step in the degradation ladder
This requirement applies to a `type: current` charger with phase switching enabled, a configured `phase_mode_entity` and a non-failed phase controller. When a phase it draws on is overloaded, the balancer SHALL degrade in this order:
1. Reduce the ampere setpoint immediately (the existing throttle).
2. Request 1-phase mode from the phase controller, but only if all of these hold:
   - the setpoint is at `min_current_a`;
   - the charger is in 3-phase mode;
   - every overloaded phase is one that 1-phase mode does not use (per `phase_1_line`);
   - the charger's EV goal is at risk, as judged by the goal-risk evaluation (no goal, or a goal on track, counts as not at risk), OR the current plan slot is solar-surplus charging for that charger (the plan's surplus kW for that charger in the current slot is above 0).
3. Pause (see "Pause below minimum current with anti-flap resume").

The goal-risk evaluation SHALL run before the balancer decides, and SHALL fail open: if it cannot be evaluated, the goal counts as at risk. The surplus-slot condition SHALL come from the plan, not from live grid export; if it cannot be read, it counts as false.

The same condition (goal at risk or surplus slot) SHALL apply when a paused charger resumes. A charger whose goal is not at risk and whose current slot is not a surplus slot SHALL resume only in its current phase mode, not in 1-phase.

A 1-phase relief request SHALL bypass the power-threshold hysteresis of the phase state machine, but SHALL still respect `phase_switch_min_dwell_s` and the phase-mode fail-safe.

When step 2 is not possible, the balancer SHALL proceed directly to step 3. These cases include:
- the goal is not at risk and the current slot is not a surplus slot;
- dwell not yet elapsed;
- the 1-phase line itself is overloaded;
- phase switching is disabled or failed;
- a `type: binary` charger.

While a relief request is outstanding, the charger SHALL be held at `min_current_a` rather than paused, unless the severe-overload rule applies. Chargers without phase switching SHALL behave exactly as before this requirement.

#### Scenario: Floor heating on L3 moves the car to L1 when the goal is at risk
- **WHEN** the charger runs 3-phase at 6 A with `phase_1_line: 1`
- **AND** L3 headroom falls to −4 A for longer than `pause_debounce_s`
- **AND** L1 has headroom for 6 A more
- **AND** the last phase change was more than `phase_switch_min_dwell_s` ago
- **AND** the goal-risk evaluation reports the goal at risk
- **THEN** the balancer SHALL request 1-phase mode instead of pausing
- **AND** charging SHALL continue on L1

#### Scenario: Goal on track pauses instead of 1-phase
- **WHEN** the same overload occurs but the goal-risk evaluation reports "goal on track"
- **THEN** the balancer SHALL NOT request 1-phase mode
- **AND** it SHALL follow the pause rule

#### Scenario: Surplus slot uses 1-phase relief when goal is on track
- **WHEN** the same overload occurs, the goal-risk evaluation reports "goal on track"
- **AND** the plan's surplus kW for this charger in the current slot is above 0
- **THEN** the balancer SHALL request 1-phase mode instead of pausing, since pausing would export the surplus

#### Scenario: Goal risk cannot be evaluated
- **WHEN** the goal-risk evaluation raises an error
- **THEN** the goal SHALL count as at risk, and 1-phase relief SHALL remain available

#### Scenario: Resume after pause stays in current mode when on track
- **WHEN** a paused charger's goal is on track, the current slot is not a surplus slot, and only the 1-phase alternative has room for `min_current_a`
- **THEN** the charger SHALL stay paused until its current phase mode fits

#### Scenario: Overload on the 1-phase line pauses instead
- **WHEN** the charger is at 6 A in 3-phase mode with `phase_1_line: 1` and L1 is the overloaded phase
- **THEN** the balancer SHALL NOT request 1-phase mode
- **AND** it SHALL follow the pause rule

#### Scenario: Dwell not elapsed
- **WHEN** a relief switch would help but the previous phase change was 200 s ago with `phase_switch_min_dwell_s: 600`
- **THEN** the balancer SHALL NOT command a phase change
- **AND** it SHALL follow the pause rule

#### Scenario: Charger without phase switching is unchanged
- **WHEN** `phase_switching_enabled` is false for the charger
- **THEN** the ladder SHALL be throttle then pause, identical to prior behavior
