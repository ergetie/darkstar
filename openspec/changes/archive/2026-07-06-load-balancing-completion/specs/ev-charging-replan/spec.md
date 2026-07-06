# Delta Spec: EV Charging Replan (load-balancing-completion)

## ADDED Requirements

### Requirement: Sustained balancer throttling triggers an early replan
The executor SHALL track, per `type: current` EV charger, the continuous duration during which the load balancer holds the charger's setpoint below the planner-derived target (or holds it paused) while the current slot plans charging for it. When this duration exceeds `load_balancing.replan_after_throttled_s` (default 600), the executor SHALL request one planner run through the same replan mechanism used by the plug-in/unplug triggers. Balancer-triggered replans SHALL be rate-limited to at most one per planner interval. The duration tracker SHALL reset whenever the setpoint reaches the planner target, when the slot no longer plans charging for that charger, or when the trigger fires. Reductions that are not caused by the balancer (planner-intended lower targets) SHALL NOT count toward the duration.

#### Scenario: EV held at floor for ten minutes triggers a replan
- **WHEN** the balancer holds a charger at 6 A against a 16 A planner target continuously for `replan_after_throttled_s`
- **THEN** the executor SHALL request one replan
- **AND** the next plan SHALL be computed from the charger's live SoC, reflecting the shortfall

#### Scenario: At most one balancer replan per planner interval
- **WHEN** a balancer-triggered replan fired and throttling persists
- **THEN** no further balancer-triggered replan SHALL fire until a full planner interval has elapsed

#### Scenario: Brief throttling does not replan
- **WHEN** the balancer reduces a charger below target for two minutes and then restores it
- **THEN** no replan SHALL be requested and the duration tracker SHALL reset

#### Scenario: Planner-intended reductions do not count
- **WHEN** the planner target itself is 6 A for a cheap-top-up slot and the balancer is idle
- **THEN** the throttled-duration tracker SHALL NOT accumulate
