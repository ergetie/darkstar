## MODIFIED Requirements

### Requirement: EV charger is throttled first using per-phase feedback
When any phase used by a charging EV has negative headroom and the fuse model's action condition holds for that phase (see `fuse-overload-timing`), the balancer SHALL reduce that charger's ampere setpoint by at least the amount that brings the worst phase down to `main_fuse_a` x `target_margin_percent` (so the phase can cool), immediately in the same tick, clamped to the charger's minimum current.

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A and the action condition holds for L1
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

#### Scenario: Car draws below its setpoint during an overload
- **WHEN** the EV has a settled 16 A setpoint, measures 10 A draw, L1 headroom is −4 A and the action condition holds for L1
- **THEN** the balancer SHALL reduce the setpoint to 6 A or lower in the same tick
- **AND** the relief folded into the pool for later entries SHALL be computed from 10 A, not 16 A

#### Scenario: Balancer never exceeds the planned charging level
- **WHEN** the planner-derived target for the current slot is 10 A and all phases have ample headroom
- **THEN** the balancer SHALL NOT raise the setpoint above 10 A

#### Scenario: Two chargers share an overloaded phase, higher-listed gives way first
- **WHEN** charger A is listed above charger B in `give_way_order`, and both draw on L1, which has −10 A headroom
- **THEN** the balancer SHALL reduce charger A toward its floor first, using as much of the −10 A deficit as charger A's headroom down to `min_current_a` can absorb
- **AND** charger B SHALL only be reduced if charger A being fully exhausted is insufficient to resolve the remaining deficit

#### Scenario: Shed load ordered above a charger gives way before the charger slows
- **WHEN** `give_way_order` lists the water heater (shed entry, declared on L2) above charger A (also on L2), and L2 headroom goes negative while the water heater is heating
- **THEN** the balancer SHALL shed the water heater first
- **AND** while the fuse model's immediate-cut condition does not hold on any phase charger A draws on, charger A SHALL hold its setpoint (never below `min_current_a`) in the tick the water heater is shed, and its setpoint SHALL only be reduced if the deficit persists after the shed relief is measured

#### Scenario: Severe overload pauses the charger even while a shed load gives way
- **WHEN** `give_way_order` lists the water heater above charger A, both on L2, the water heater is shed this tick, and the fuse model's immediate-cut condition holds on L2 (safety-scaled trip time shorter than `executor.interval_seconds`)
- **THEN** the balancer SHALL pause charger A in the same tick instead of holding for the unmeasured shed relief
- **AND** charger A SHALL resume only through the normal quick re-fit rules (confirm window, target margin)
#### Scenario: Single dynamically-throttled charger is unaffected by ordering
- **WHEN** only one `type: current` EV charger is configured and no shed loads exist
- **THEN** its position in `give_way_order` SHALL have no observable effect on balancer behavior

#### Scenario: Throttle computed from effective baseline
- **WHEN** the balancer reduces or holds a charger's setpoint
- **THEN** the reduction, any hold, and the relief the charger contributes to the shared headroom pool SHALL be computed from the charger's effective baseline (see `ev-measured-draw`) rather than the last commanded setpoint
- **AND** when no measurement exists the effective baseline equals the commanded setpoint

#### Scenario: Raising the setpoint with positive headroom
- **WHEN** headroom is positive
- **THEN** the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`

#### Scenario: Top-down give-way ordering
- **WHEN** a phase is overloaded and several balanced loads draw on it
- **THEN** give-way ordering across ALL balanced loads SHALL be governed by the single ordered list `load_balancing.give_way_order` (see the `load-balancing-settings` capability)
- **AND** the balancer SHALL process entries top-down, and an entry SHALL only be asked to give way once every entry above it that draws on the overloaded phase(s) is exhausted (a charger entry is exhausted when paused; a shed entry when shed)
- **AND** when multiple entries could give way in the same tick, list position, not device kind, SHALL decide the order
- **AND** a charger entry gives way by immediate setpoint reduction toward its `min_current_a`

#### Scenario: Charger holds while a shed entry above gives way
- **WHEN** a shed entry above a charger gives way in the current tick on a phase the charger draws on, so its relief is not yet measured
- **THEN** the charger SHALL hold its setpoint for that tick instead of reducing or pausing
- **AND** unless the fuse model's immediate-cut condition holds on a phase the charger draws on, in which case the charger SHALL pause immediately; an immediate-cut condition always takes precedence over the hold

#### Scenario: Backward-compatible behavior of give-way ordering
- **WHEN** a household's order matches the migrated default (all current-type chargers before all shed loads)
- **THEN** it SHALL behave exactly as the previous two-tier system
- **AND** a household with a single dynamically-throttled charger and no shed loads SHALL behave exactly as before this requirement was introduced

### Requirement: Pause below minimum current with anti-flap resume
When a charger is at its minimum current (`min_current_a`, default 6 A, the IEC 61851 floor) and is the frontmost non-exhausted `give_way_order` entry on a phase that remains overloaded, the balancer SHALL first attempt the 1-phase relief step where eligible (see "1-phase relief step in the degradation ladder").

#### Scenario: Heavy load forces a pause
- **WHEN** available headroom on a phase the EV uses stays below 6 A worth of charging, the fuse model's action condition holds for that phase, no higher-listed entry can give way, and 1-phase relief is not possible
- **THEN** the balancer SHALL stop the charging session
#### Scenario: One-second spike does not pause
- **WHEN** the charger is at 6 A and L3 headroom goes to −3 A for 1 s, then recovers
- **THEN** the balancer SHALL NOT pause charging

#### Scenario: Severe overload pauses immediately
- **WHEN** the charger is at 6 A and L3 reads 80 A with `main_fuse_a: 16` (5x, an instant trip on both preset curves)
- **THEN** the balancer SHALL pause in the same tick without waiting for accumulated heat
#### Scenario: Brief dip does not cause rapid restart cycling
- **WHEN** charging was paused and headroom recovers for a single tick, then falls back below the minimum current
- **THEN** charging SHALL NOT resume, and the confirm window SHALL start over the next time the phases fit

#### Scenario: Quick re-fit after the confirm window
- **WHEN** `main_fuse_a` is 16 A, the charger paused on an L3 spike, and all phases have read 5 A for 10 s
- **THEN** the charger SHALL resume in the same tick, without waiting for `resume_delay_s`
- **AND** its setpoint SHALL be the largest that fits within 13.6 A per phase, capped by the planner target

#### Scenario: Re-fit into 1-phase when only the 1-phase line fits
- **WHEN** a 3-phase charger with `phase_1_line: 1` is paused, L3 still has no room for 6 A within the target margin, L1 has had room for 6 A for 10 s, and 600 s have passed since the last phase change
- **THEN** the balancer SHALL request 1-phase mode and resume the charger on L1

#### Scenario: Stay paused when dwell has not elapsed
- **WHEN** only L1 fits but the last phase change was 200 s ago with `phase_switch_min_dwell_s: 600`
- **THEN** the charger SHALL stay paused until either its current mode fits or the dwell elapses

#### Scenario: Repeated pauses lengthen the confirm window
- **WHEN** a charger re-fits and pauses again within 10 minutes, twice in a row
- **THEN** the next confirm windows SHALL be 30 s and then 120 s
- **AND** after a pause more than 10 minutes after its last re-fit, the confirm window SHALL be `resume_confirm_s` again

#### Scenario: Charger is not paused while a higher-listed shed load can still give way
- **WHEN** charger A is at its floor, the phase remains overloaded, and a shed entry listed above charger A on that phase has not yet been shed
- **THEN** the balancer SHALL shed that load before pausing charger A

#### Scenario: Pause only after debounced persistent overload
- **WHEN** a charger at `min_current_a` remains overloaded and the 1-phase relief step is not applicable
- **THEN** it SHALL pause charging only once the fuse model's action condition holds for the worst phase (heat at `fuse_safety_percent` of the trip time), holding `min_current_a` meanwhile
- **AND** the same applies when the binding headroom cannot sustain even the minimum current and no entry above the charger can still give way
- **AND** heat SHALL cool and no pause SHALL be requested when the phase returns to or below its fuse rating before the action condition holds
#### Scenario: Severe overload pauses immediately
- **WHEN** any phase the charger draws on meets the fuse model's immediate-cut condition
- **THEN** the pause SHALL be immediate
#### Scenario: Pause semantics and minimum current floor
- **WHEN** the balancer pauses a charger
- **THEN** the balancer SHALL NEVER set a setpoint below `min_current_a`
- **AND** a pause stops charging through the charger's switch entity as defined by `ev-current-control` "Minimum current floor with pause semantics" and SHALL NOT be expressed as a 0 A or sub-floor setpoint

#### Scenario: Paused charger re-fit check
- **WHEN** a charger is paused
- **THEN** the balancer SHALL re-check every tick, on the momentary reading of each phase, whether the charger fits: a phase mode fits when every phase it would draw on has room for `min_current_a` without exceeding `target_margin_percent` of `main_fuse_a` (after this tick's decisions for entries above it)
- **AND** once a mode has fitted continuously for the confirm window (`resume_confirm_s`, default 10 s), with fresh sensor readings throughout, the charger SHALL re-fit as in the next scenario

#### Scenario: Re-fit phase mode selection
- **WHEN** the confirm window has elapsed
- **THEN** (a) the charger SHALL re-fit in its current phase mode when that mode fits
- **AND** (b) otherwise in 1-phase mode on `phase_1_line`, when the charger is in 3-phase mode, 1-phase on that line fits, phase switching is available and `phase_switch_min_dwell_s` has elapsed since the last phase change, through the 1-phase relief demand, and only if the switch is actually applied
- **AND** (c) otherwise it SHALL stay paused and keep checking

#### Scenario: Resume setpoint and ordering
- **WHEN** a paused charger resumes
- **THEN** it SHALL resume at the largest whole ampere setpoint that fits on the chosen mode's phases within the target margin, never below `min_current_a` and never above `min(max_current_a, planner-derived amps)`
- **AND** it SHALL then ramp through the averaged gate of "Asymmetric ramping with resume margin"
- **AND** resume SHALL still respect `give_way_order` reverse-order restore
- **AND** the return from 1-phase to 3-phase SHALL stay governed by the averaged gate and dwell (`ev-phase-switching`)

#### Scenario: Anti-flap back-off
- **WHEN** a charger pauses again within 10 minutes of a re-fit
- **THEN** its next confirm window SHALL grow one step: `resume_confirm_s`, then 30 s, then 120 s (each never shorter than `resume_confirm_s`)
- **AND** a pause more than 10 minutes after the last re-fit SHALL reset the window to `resume_confirm_s`
- **AND** `resume_delay_s` SHALL NOT gate the re-fit

### Requirement: 1-phase relief step in the degradation ladder
This requirement applies to a `type: current` charger with phase switching enabled, a configured `phase_mode_entity` and a non-failed phase controller. When a phase it draws on is overloaded, the balancer SHALL degrade in this order: first reduce the ampere setpoint immediately (the existing throttle); second request 1-phase mode from the phase controller, but only if all eligibility conditions in the scenarios below hold; third pause (see "Pause below minimum current with anti-flap resume").

#### Scenario: Floor heating on L3 moves the car to L1 when the goal is at risk
- **WHEN** the charger runs 3-phase at 6 A with `phase_1_line: 1`
- **AND** L3 headroom falls to −4 A and the fuse model's action condition holds for L3
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

#### Scenario: 1-phase relief eligibility conditions
- **WHEN** the balancer evaluates step 2 of the degradation ladder (request 1-phase mode)
- **THEN** the setpoint SHALL be at `min_current_a`
- **AND** the charger SHALL be in 3-phase mode
- **AND** every overloaded phase SHALL be one that 1-phase mode does not use (per `phase_1_line`)
- **AND** the charger's EV goal SHALL be at risk, as judged by the goal-risk evaluation (no goal, or a goal on track, counts as not at risk), OR the current plan slot SHALL be solar-surplus charging for that charger (the plan's surplus kW for that charger in the current slot is above 0)

#### Scenario: Goal-risk evaluation fails open
- **WHEN** the goal-risk evaluation runs
- **THEN** it SHALL run before the balancer decides, and SHALL fail open: if it cannot be evaluated, the goal counts as at risk
- **AND** the surplus-slot condition SHALL come from the plan, not from live grid export; if it cannot be read, it counts as false

#### Scenario: Resume uses the same relief condition
- **WHEN** a paused charger resumes
- **THEN** the same condition (goal at risk or surplus slot) SHALL apply
- **AND** a charger whose goal is not at risk and whose current slot is not a surplus slot SHALL resume only in its current phase mode, not in 1-phase

#### Scenario: Relief request bypasses hysteresis but not dwell
- **WHEN** a 1-phase relief request is made
- **THEN** it SHALL bypass the power-threshold hysteresis of the phase state machine
- **AND** it SHALL still respect `phase_switch_min_dwell_s` and the phase-mode fail-safe

#### Scenario: Relief step not possible falls through to pause
- **WHEN** step 2 is not possible, because the goal is not at risk and the current slot is not a surplus slot, dwell has not yet elapsed, the 1-phase line itself is overloaded, phase switching is disabled or failed, or the charger is a `type: binary` charger
- **THEN** the balancer SHALL proceed directly to step 3 (pause, see "Pause below minimum current with anti-flap resume")

#### Scenario: Relief request outstanding
- **WHEN** a relief request is outstanding
- **THEN** the charger SHALL be held at `min_current_a` rather than paused, unless the severe-overload rule applies
- **AND** chargers without phase switching SHALL behave exactly as before this requirement

### Requirement: Ramp-up hold-off after a setpoint reduction

After the balancer reduces an EV charger's setpoint for any reason (throttle, floor degrade, 1-phase relief), it SHALL NOT increase that charger's setpoint until the worst phase the charger draws on has cooled below 50% fuse heat (see `fuse-overload-timing`); `ramp_up_window_s` remains only the averaging window for increases. Reductions SHALL NOT be delayed by the hold-off. The hold-off SHALL be cleared when the charger's plan ends or it is paused.

#### Scenario: New house load does not cause a sawtooth
- **WHEN** a water heater starts on L3 and the balancer reduces the charger from 10 A to 8 A at 12:39:20
- **AND** the 60 s average of L3 still leaves room because it contains samples from before the load started
- **THEN** the balancer SHALL NOT raise the setpoint while the worst phase still has 50% or more heat

#### Scenario: Ramp resumes after the hold-off
- **WHEN** the worst phase has cooled below 50% heat and the averaged current plus the increase stays within the target margin
- **THEN** the balancer SHALL raise the setpoint by at most `increase_step_a` per tick

#### Scenario: A further reduction restarts the hold-off
- **WHEN** the balancer reduces the setpoint again during the hold-off
- **THEN** the hold-off SHALL restart from the new reduction

#### Scenario: Reductions are never held
- **WHEN** the fuse model's action condition holds on a phase during the hold-off
- **THEN** the balancer SHALL reduce the setpoint in the same tick

### Requirement: Battery charge ramps back after relief
After a reduction the balancer SHALL NOT raise the battery cap until the worst battery phase has cooled below 50% fuse heat (`ramp_up_window_s` remains only the averaging window). Later raises SHALL be `increase_step_a` per phase, only while each battery phase's averaged current plus the raise stays within `target_margin_percent` of `main_fuse_a`, and never above the plan. A paused battery SHALL restore in reverse list order and resume after its phases fit the minimum charge for `resume_confirm_s`.

#### Scenario: Relief after the washing machine stops
- **WHEN** the battery was throttled and the averaged L1 current has dropped well below the target margin and the worst battery phase has cooled below 50% heat
- **THEN** the cap SHALL rise stepwise toward the plan and never exceed it

#### Scenario: Paused battery blocks restores above it
- **WHEN** the battery is paused and a shed load listed above it is shed
- **THEN** the shed load SHALL NOT be restored before the battery resumes

### Requirement: Battery grid charging gives way in the user-ordered list
When `give_way_order` contains a `battery` entry, the balancer SHALL treat battery grid charging as a give-way entry at that position, drawing on all three phases (the inverter is assumed to be 3-phase). When a battery phase still has negative pool headroom and the fuse model's action condition holds (also while holding for shed relief) after the entries above have given way, the balancer SHALL cut the charge cap by the remaining deficit spread evenly over those phases, within zero and the planned value, and fold the relief into the pool.

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

### Requirement: Target safety margin
The balancer SHALL steer every phase a balanced load draws on toward `target_margin_percent` of `main_fuse_a` (default 85 %), not toward 100 %. It SHALL NOT raise any setpoint, restore any shed load, or return a charger from 1-phase to 3-phase if doing so would push a phase's projected averaged current (see "Asymmetric ramping with resume margin") above that target.

#### Scenario: Quiet night leaves room for full charging
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, the house draws 2 A per phase, and the planner target is 10 A
- **THEN** the balancer SHALL ramp the charger to 10 A (projected 12 A ≤ 13.6 A)

#### Scenario: Ramp-up stops at the target, not at the fuse
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, and the averaged L1 current with the charger at 8 A is 13 A
- **THEN** the balancer SHALL NOT raise the setpoint to 9 A (projected 14 A > 13.6 A)
- **AND** it SHALL NOT reduce the setpoint either, because L1 is below `main_fuse_a`

#### Scenario: No resume above the target margin
- **WHEN** the balancer resumes a paused charger
- **THEN** it SHALL NOT resume at a current that would push a phase's momentary current above that target (see "Pause below minimum current with anti-flap resume")

#### Scenario: Target margin does not trigger reductions
- **WHEN** a phase is between the target and `main_fuse_a`
- **THEN** the target SHALL NOT itself trigger a reduction: the phase holds its current setpoints
- **AND** reductions SHALL continue to be triggered only by the fuse model's action condition, measured against `main_fuse_a` and not the target margin
