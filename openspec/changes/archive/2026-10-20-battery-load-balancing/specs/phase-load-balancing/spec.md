## ADDED Requirements

### Requirement: Battery grid charging gives way in the user-ordered list
When `give_way_order` contains a `battery` entry, the balancer SHALL treat battery grid charging as a give-way entry at that position, drawing on all three phases (the inverter is assumed to be 3-phase). When a battery phase still has negative pool headroom after the entries above have given way, the balancer SHALL cut the charge cap by the remaining deficit spread evenly over those phases, within zero and the planned value, and fold the relief into the pool.

#### Scenario: Washing machine pushes one phase over during grid charging
- **WHEN** `main_fuse_a` is 20, the inverter is 3-phase, the plan grid-charges at 10 kW, and L1 reads 24 A with no other entry able to give way
- **THEN** the balancer SHALL cut the battery cap by about 4 A × 230 V × 3 phases (2760 W, limited to the reducible grid share)
- **AND** entries listed below the battery SHALL see no remaining L1 deficit from that overload

#### Scenario: Reduction spread over all phases
- **WHEN** only L2 is 3 A over the limit and no entry above can give way
- **THEN** the cap SHALL be reduced by about 3 A × 230 V × 3

#### Scenario: Entry above the battery relieves first
- **WHEN** a charger listed above the battery can absorb the whole deficit
- **THEN** the battery cap SHALL stay unchanged

### Requirement: Only grid-sourced battery charging is reduced
The battery entry SHALL act only while the controller's mode intent is `charge` (planned grid charging). The reducible amount SHALL be limited to the grid-sourced charge: the minimum of the current cap, the measured grid import, and the battery's measured charge power when a `battery_power` sensor is configured. Discharge, export and `self_consumption` PV charging SHALL never be changed by the balancer.

#### Scenario: Self-consumption slot
- **WHEN** the mode intent is `self_consumption` and a phase is over the limit
- **THEN** the battery entry SHALL report idle and leave `charge_value` unchanged

#### Scenario: PV covers the battery
- **WHEN** the mode intent is `charge` but grid import is 0 W
- **THEN** the battery cap SHALL NOT be reduced

### Requirement: Battery cap is applied through the profile charge value
The executor SHALL apply the battery cap by lowering `ControllerDecision.charge_value` before profile dispatch, in the profile's `control_unit` (amps converted with the battery nominal voltage), rounded down to the profile step. When the capped value is below the profile's minimum charge value, the executor SHALL dispatch `idle` instead of `charge` for that tick. No profile writes beyond the chosen mode SHALL be added.

#### Scenario: Deye amps profile
- **WHEN** the profile `control_unit` is `A`, the battery nominal voltage is 48 V, `round_step_a` is 5, and the cap is 7200 W
- **THEN** `charge_value` SHALL be 150 A

#### Scenario: Cap below minimum
- **WHEN** the capped value is below `min_charge_a` (or `min_charge_w`)
- **THEN** the executor SHALL dispatch `idle` and report the battery as paused

### Requirement: Battery charge ramps back after relief
After a reduction the balancer SHALL NOT raise the battery cap for `ramp_up_window_s`. Later raises SHALL be `increase_step_a` per phase, only while each battery phase's averaged current plus the raise stays within `target_margin_percent` of `main_fuse_a`, and never above the plan. A paused battery SHALL restore in reverse list order and resume after its phases fit the minimum charge for `resume_confirm_s`.

#### Scenario: Relief after the washing machine stops
- **WHEN** the battery was throttled and the averaged L1 current has dropped well below the target margin for longer than `ramp_up_window_s`
- **THEN** the cap SHALL rise stepwise toward the plan and never exceed it

#### Scenario: Paused battery blocks restores above it
- **WHEN** the battery is paused and a shed load listed above it is shed
- **THEN** the shed load SHALL NOT be restored before the battery resumes

### Requirement: Battery entry under stale phase sensors
When any phase the battery draws on is stale, the balancer SHALL keep the battery cap at its current value: no raise and no further reduction from that phase.

#### Scenario: Stale L1 while throttled
- **WHEN** the battery is capped at 6 kW and L1 becomes stale
- **THEN** the cap SHALL stay at 6 kW until L1 is fresh again

### Requirement: Sustained battery throttle triggers a replan
The executor SHALL track how long the battery cap has been held below the planned value, or paused, during a `charge` intent. Once that duration reaches `replan_after_throttled_s`, it SHALL request one early replan, subject to the same per-planner-interval rate limit as chargers.

#### Scenario: Throttled for ten minutes
- **WHEN** the battery has been capped below the plan continuously for 600 s with the default settings
- **THEN** one balancer-triggered replan SHALL be requested

### Requirement: Battery interventions do not notify
Battery throttle, pause and resume SHALL NOT send `notify_interventions` notifications.

#### Scenario: Battery paused with notifications enabled
- **WHEN** `notify_interventions` is true and the balancer pauses battery grid charging
- **THEN** no intervention notification SHALL be sent for the battery
