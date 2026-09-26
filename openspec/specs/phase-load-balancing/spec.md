# Spec: Phase Load Balancing

## Purpose

Defines how the executor keeps per-phase grid current within the main fuse rating by throttling, pausing, and shedding balanced loads (EV chargers, water heater, custom entities) in real time, using per-phase current measurements independent of the planner's total-kW budget.
## Requirements
### Requirement: Per-phase headroom computation
When load balancing is enabled, the executor SHALL compute per-phase headroom on every tick as `main_fuse_a − measured_grid_current_a` for each of L1, L2, L3, using current magnitude (direction-independent). The binding headroom for a load SHALL be the minimum headroom across the phases that load draws on.

For each phase, `measured_grid_current_a` SHALL be derived from whichever sensor kind is configured for that phase, auto-detected from the configured entity's `unit_of_measurement`/`device_class` attributes (no manual mode setting):
- If the entity's unit indicates current (A), its state SHALL be used directly as `measured_grid_current_a`.
- If the entity's unit indicates power (W or kW), the reading SHALL be normalized to a common power unit and converted via `measured_grid_current_a = power_w / voltage_v`, where `voltage_v` is that phase's configured voltage entity if present and fresh, otherwise `load_balancing.nominal_voltage_v`.
- If the entity's unit cannot be recognized as current or power, this SHALL be a startup validation error (see `load-balancing-settings`), not a silent fallback.

#### Scenario: Unbalanced house load limits one phase
- **WHEN** `main_fuse_a` is 20 and measured grid currents are L1=18 A, L2=5 A, L3=5 A
- **THEN** headroom SHALL be computed as L1=2 A, L2=15 A, L3=15 A
- **AND** the binding headroom for a 3-phase EV charger SHALL be 2 A

#### Scenario: Total power within limits but one phase over fuse
- **WHEN** total grid power is below `system.grid.max_power_kw` equivalents
- **AND** L1 measured current exceeds `main_fuse_a`
- **THEN** the balancer SHALL still act to reduce L1 loading (per-phase, not total-kW, governs)

#### Scenario: Power sensor with real per-phase voltage
- **WHEN** L1's configured sensor reports 2760 W and L1's configured voltage entity reports 230 V
- **THEN** `measured_grid_current_a` for L1 SHALL be computed as 12 A

#### Scenario: Power sensor with no voltage entity configured
- **WHEN** L2's configured sensor reports 1610 W (power) and no voltage entity is configured for L2
- **AND** `load_balancing.nominal_voltage_v` is 220
- **THEN** `measured_grid_current_a` for L2 SHALL be computed as 1610 / 220 ≈ 7.3 A

#### Scenario: Power sensor reporting kW is normalized before conversion
- **WHEN** L3's configured sensor reports 2.3 kW and voltage resolves to 230 V
- **THEN** the reading SHALL be normalized to 2300 W before conversion, yielding `measured_grid_current_a` ≈ 10 A

#### Scenario: Mixed sensor kinds across phases
- **WHEN** L1 is configured with a current sensor, and L2/L3 are configured with power sensors plus voltage entities
- **THEN** each phase's `measured_grid_current_a` SHALL be derived independently per its own detected kind

#### Scenario: Unrecognized sensor unit
- **WHEN** a phase's configured sensor reports a unit that is neither a recognized current nor power unit
- **THEN** startup validation SHALL fail naming that phase's sensor and its unexpected unit

### Requirement: EV charger is throttled first using per-phase feedback
When any phase used by a charging EV has negative headroom, the balancer SHALL reduce that charger's ampere setpoint by at least the magnitude of the worst negative headroom, immediately in the same tick, clamped to the charger's minimum current. The reduction, any hold, and the relief the charger contributes to the shared headroom pool SHALL be computed from the charger's effective baseline (see `ev-measured-draw`) rather than the last commanded setpoint; when no measurement exists the effective baseline equals the commanded setpoint. When headroom is positive, the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`.

Give-way ordering across ALL balanced loads SHALL be governed by the single ordered list `load_balancing.give_way_order` (see the `load-balancing-settings` capability): the balancer SHALL process entries top-down, and an entry SHALL only be asked to give way once every entry above it that draws on the overloaded phase(s) is exhausted (a charger entry is exhausted when paused; a shed entry when shed). A charger entry gives way by immediate setpoint reduction toward its `min_current_a`. When a shed entry above a charger gives way in the current tick on a phase the charger draws on, its relief is not yet measured, so the charger SHALL hold its setpoint for that tick instead of reducing or pausing — unless a phase the charger draws on reads above `severe_overload_percent` of `main_fuse_a`, in which case the charger SHALL pause immediately; a severe overload always takes precedence over the hold. When multiple entries could give way in the same tick, list position — not device kind — SHALL decide the order. A household whose order matches the migrated default (all current-type chargers before all shed loads) SHALL behave exactly as the previous two-tier system, and a household with a single dynamically-throttled charger and no shed loads SHALL behave exactly as before this requirement was introduced.

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

#### Scenario: Car draws below its setpoint during an overload
- **WHEN** the EV has a settled 16 A setpoint, measures 10 A draw, and L1 headroom is −4 A
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
- **AND** while every phase charger A draws on reads at or below `severe_overload_percent` of `main_fuse_a`, charger A SHALL hold its setpoint (never below `min_current_a`) in the tick the water heater is shed, and its setpoint SHALL only be reduced if the deficit persists after the shed relief is measured

#### Scenario: Severe overload pauses the charger even while a shed load gives way
- **WHEN** `give_way_order` lists the water heater above charger A, both on L2, the water heater is shed this tick, and L2 reads above `severe_overload_percent` of `main_fuse_a` (default 125 %)
- **THEN** the balancer SHALL pause charger A in the same tick instead of holding for the unmeasured shed relief
- **AND** charger A SHALL resume only through the normal quick re-fit rules (confirm window, target margin)

#### Scenario: Single dynamically-throttled charger is unaffected by ordering
- **WHEN** only one `type: current` EV charger is configured and no shed loads exist
- **THEN** its position in `give_way_order` SHALL have no observable effect on balancer behavior

### Requirement: Asymmetric ramping with resume margin
Setpoint decreases SHALL be applied immediately, without rate limit, and SHALL be computed from the momentary per-phase reading of the current tick. Setpoint increases SHALL be rate-limited to `increase_step_a` per tick (default 1 A). They SHALL be computed from a rolling average of each phase's current over `ramp_up_window_s` (default 60 s). They SHALL only occur when, for every phase the load draws on, the averaged current plus the increase stays at or below `target_margin_percent` of `main_fuse_a` (see "Target safety margin"). An increase SHALL also never exceed the phase's momentary headroom against `main_fuse_a` on the current tick. Restoring a shed load and returning a charger from 1-phase to 3-phase SHALL use the same averaged reading and target; resuming a paused charger follows "Pause below minimum current with anti-flap resume". Until a phase has `ramp_up_window_s` of fresh samples (e.g. after startup or a stale-sensor episode), increases on that phase SHALL NOT occur.

#### Scenario: Load hovers just under the fuse limit
- **WHEN** the averaged L1 current sits at 95 % of `main_fuse_a` with `target_margin_percent: 85`
- **THEN** the balancer SHALL NOT increase the EV setpoint
- **AND** charging continues at the current reduced level

#### Scenario: Headroom recovers
- **WHEN** all phases' averaged currents drop below the target margin and remain there
- **THEN** the balancer SHALL raise the setpoint by at most `increase_step_a` per tick until the planner-derived target is reached or the target margin would be exceeded

#### Scenario: One-second spike does not unwind a ramp-up decision
- **WHEN** L2 momentarily jumps to 15 A for one tick while its 60 s average is 9 A, and the momentary reading does not exceed `main_fuse_a`
- **THEN** the balancer SHALL NOT reduce the setpoint
- **AND** the spike SHALL only affect ramp-up decisions through its share of the average

#### Scenario: Decrease uses the momentary reading
- **WHEN** L1's momentary reading is 19 A with `main_fuse_a: 16` while its 60 s average is 12 A
- **THEN** the balancer SHALL reduce the setpoint by at least 3 A in the same tick

### Requirement: Pause below minimum current with anti-flap resume
When a charger is at its minimum current (`min_current_a`, default 6 A, the IEC 61851 floor) and is the frontmost non-exhausted `give_way_order` entry on a phase that remains overloaded, the balancer SHALL first attempt the 1-phase relief step where eligible (see "1-phase relief step in the degradation ladder"). Otherwise it SHALL pause charging only after the overload has persisted continuously for `pause_debounce_s` (default 5 s), holding `min_current_a` meanwhile. The same applies when the binding headroom cannot sustain even the minimum current and no entry above the charger can still give way.

The pause SHALL be immediate, without debounce, when any phase the charger draws on reads above `severe_overload_percent` of `main_fuse_a` (default 125 %). The overload timer SHALL reset whenever the phase returns to non-negative headroom. The balancer SHALL NEVER set a setpoint below `min_current_a`. A pause stops charging through the charger's switch entity as defined by `ev-current-control` "Minimum current floor with pause semantics" and SHALL NOT be expressed as a 0 A or sub-floor setpoint.

While paused, the balancer SHALL re-check every tick, on the momentary reading of each phase, whether the charger fits: a phase mode fits when every phase it would draw on has room for `min_current_a` without exceeding `target_margin_percent` of `main_fuse_a` (after this tick's decisions for entries above it). Once a mode has fitted continuously for the confirm window (`resume_confirm_s`, default 10 s), with fresh sensor readings throughout, the charger SHALL re-fit:
- (a) in its current phase mode when that mode fits;
- (b) otherwise in 1-phase mode on `phase_1_line`, when the charger is in 3-phase mode, 1-phase on that line fits, phase switching is available and `phase_switch_min_dwell_s` has elapsed since the last phase change — through the 1-phase relief demand, and only if the switch is actually applied;
- (c) otherwise it SHALL stay paused and keep checking.

The charger SHALL resume at the largest whole ampere setpoint that fits on the chosen mode's phases within the target margin, never below `min_current_a` and never above `min(max_current_a, planner-derived amps)`, and SHALL then ramp through the averaged gate of "Asymmetric ramping with resume margin". Resume SHALL still respect `give_way_order` reverse-order restore. The return from 1-phase to 3-phase SHALL stay governed by the averaged gate and dwell (`ev-phase-switching`).

Anti-flap back-off: when a charger pauses again within 10 minutes of a re-fit, its next confirm window SHALL grow one step — `resume_confirm_s`, then 30 s, then 120 s (each never shorter than `resume_confirm_s`). A pause more than 10 minutes after the last re-fit SHALL reset the window to `resume_confirm_s`. `resume_delay_s` SHALL NOT gate the re-fit.

#### Scenario: Heavy load forces a pause
- **WHEN** available headroom on a phase the EV uses stays below 6 A worth of charging for longer than `pause_debounce_s`, no higher-listed entry can give way, and 1-phase relief is not possible
- **THEN** the balancer SHALL stop the charging session

#### Scenario: One-second spike does not pause
- **WHEN** the charger is at 6 A and L3 headroom goes to −3 A for 1 s, then recovers
- **THEN** the balancer SHALL NOT pause charging

#### Scenario: Severe overload pauses immediately
- **WHEN** the charger is at 6 A and L3 reads 21 A with `main_fuse_a: 16` (131 %)
- **THEN** the balancer SHALL pause in the same tick without waiting for `pause_debounce_s`

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

### Requirement: Prioritized shedding and reverse-order restore of on/off loads
A shed entry in `give_way_order` SHALL give way by switching its load off once every entry above it drawing on the overloaded phase(s) is exhausted, per the top-down processing defined in "EV charger is throttled first using per-phase feedback". Shedding a water heater SHALL use its existing minimum-target actuation; shedding a custom entity SHALL write its configured off value; shedding a `type: binary` EV charger SHALL turn off its switch entity. A `type: current` EV charger SHALL NOT appear as a shed entry — it participates exclusively as a charger (throttle/pause) entry. Restore SHALL happen in exact reverse `give_way_order` (the last entry to give way is restored first), across chargers and shed loads alike. A shed load SHALL be restored only after `resume_delay_s` has elapsed and its phases have headroom within the target margin; a paused charger SHALL resume per the quick re-fit rules of "Pause below minimum current with anti-flap resume".

#### Scenario: EV at floor is not enough
- **WHEN** every entry above the water heater in `give_way_order` is exhausted and L2 remains over `main_fuse_a`
- **AND** the water heater (declared on L2) is heating
- **THEN** the balancer SHALL shed the water heater

#### Scenario: Restore order is reverse of give-way order
- **WHEN** two entries gave way (the higher-listed first, then the lower-listed) and headroom recovers durably
- **THEN** the lower-listed entry SHALL be restored before the higher-listed entry
- **AND** each restore SHALL wait for its own conditions (confirm window for a charger, resume delay and margin for a shed load)

### Requirement: Stale sensor fail-safe
If any per-phase grid current value is missing or older than `sensor_stale_after_s` (default 30 s), the balancer SHALL immediately reduce the EV to `min_current_a`. If staleness persists beyond one resume cycle (`resume_delay_s`), the balancer SHALL pause charging. Balancing decisions SHALL never be made from stale data as if it were fresh.

A reading's age SHALL be measured from its reading-freshness timestamp as defined by the `ha-reading-freshness` capability (`last_reported`, falling back to `last_updated`, then `last_changed`) — i.e., from when HA last received a report, not from when the value last changed. A sensor that keeps reporting an unchanged value SHALL NOT be considered stale.

For a phase in power-sensor mode with a configured voltage entity, "the per-phase grid current value" for staleness purposes SHALL be considered stale if either the power reading or the voltage reading is missing or older than `sensor_stale_after_s` — i.e., the fail-safe SHALL use the older of the two readings' timestamps. A phase with no voltage entity configured is not affected by this rule (it always uses the nominal fallback voltage, which has no staleness of its own).

#### Scenario: Phase sensor stops updating mid-charge
- **WHEN** the L1 sensor's last report is older than 30 s while the EV charges at 16 A
- **THEN** the balancer SHALL set the EV to 6 A
- **AND** if data is still stale 120 s later, charging SHALL be stopped

#### Scenario: Steady value still reported is not stale
- **WHEN** the L3 power reading has not changed for 45 s but its `last_reported` is 5 s old
- **THEN** L3 SHALL NOT be treated as stale and no fail-safe or notification SHALL occur

#### Scenario: Configured voltage entity goes stale
- **WHEN** L2 is in power-sensor mode with a configured voltage entity, the power reading is fresh, but the voltage entity's last report is older than `sensor_stale_after_s`
- **THEN** L2 SHALL be treated as stale by this fail-safe (same as a stale current/power reading)
- **AND** the balancer SHALL NOT substitute `load_balancing.nominal_voltage_v` in place of the stale voltage entity

#### Scenario: No voltage entity configured is not staleness
- **WHEN** L3 is in power-sensor mode with no voltage entity configured, and the power reading is fresh
- **THEN** L3 SHALL NOT be considered stale on account of having no voltage entity
- **AND** `load_balancing.nominal_voltage_v` SHALL be used for the conversion

### Requirement: Feature gating
Load balancing SHALL run only when `load_balancing.enabled` is true and prerequisites are configured (fuse rating, per-phase sensors, at least one balanced load). When disabled or unconfigured, executor behavior SHALL be identical to the pre-change system, including binary EV control.

#### Scenario: User without per-phase sensors
- **WHEN** `load_balancing.enabled` is false
- **THEN** no balancer logic runs and scheduled EV charging operates as today

### Requirement: Execution log throttling at high tick frequency
The executor SHALL write an execution-log record only when the tick produced a change (mode intent, dispatched action, override or balancer state transition), plus a heartbeat record at least once per 15-minute slot. Every balancer state transition (throttle start/stop, shed, restore, pause, resume, stale-data fallback) SHALL be logged with a human-readable reason.

The execution history UI SHALL disclose this recording policy: it SHALL display the time and outcome of the most recent executor tick (even when that tick produced no record) and state that only changes plus one heartbeat per slot are recorded, so a sparse history reads as a quiet system rather than a dead one.

#### Scenario: Idle 5-second ticks do not flood the database
- **WHEN** the executor ticks every 5 s and nothing changes for a full slot
- **THEN** at most one heartbeat record SHALL be written for that slot

#### Scenario: Balancer intervention is always auditable
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 headroom went negative
- **THEN** an execution-log record SHALL be written including the reason and per-phase currents

#### Scenario: Quiet history explains itself
- **WHEN** the executor has ticked for hours without producing a change record
- **THEN** the execution history page SHALL show the last tick's time and outcome and state the change-only recording policy
- **AND** the page SHALL NOT present an empty list with no explanation

### Requirement: Balancer intervention notifications
When `load_balancing.notify_interventions` is true, the balancer SHALL send user notifications through the existing notification path (Home Assistant notify service with Discord webhook fallback) as follows:
- **Always notify:** a load is shed, or the stale-sensor fail-safe engages.
- **Charger pause:** notify only when the pause puts an active EV goal at risk. A goal is at risk when the charger has an active goal (deadline and positive required energy) and the most recent planner `ev_goal_diagnostics` for that charger report a shortfall or at-risk status, or when the pause occurs inside a slot the plan scheduled for goal charging within 2 hours of the deadline. Pauses that do not put a goal at risk SHALL NOT notify; they are recorded in the execution log only.
- **Never notify:** routine throttle adjustments, ramp-ups, and 1-phase relief switches.

Each qualifying transition SHALL produce at most one notification (no per-tick repeats), carrying the same human-readable reason as its execution-log record. The default for `notify_interventions` SHALL be false.

#### Scenario: Water heater is shed overnight
- **WHEN** `notify_interventions` is true and the balancer sheds the water heater because L2 stayed over the fuse with all higher-listed entries exhausted
- **THEN** one notification SHALL be sent naming the water heater and the reason

#### Scenario: Routine throttling does not notify
- **WHEN** the balancer reduces a charger from 16 A to 12 A and later ramps it back
- **THEN** no notification SHALL be sent

#### Scenario: Pause without goal risk does not notify
- **WHEN** the charger pauses three times during an afternoon while its goal is 30 hours away and diagnostics show no shortfall
- **THEN** no notification SHALL be sent
- **AND** each pause SHALL still be recorded in the execution log

#### Scenario: Pause that threatens the goal notifies
- **WHEN** the charger pauses at 21:30 during goal-scheduled charging with the deadline at 23:00
- **THEN** one notification SHALL be sent naming the charger, the reason, and that the goal is at risk

#### Scenario: Feature defaults off
- **WHEN** a user upgrades without touching config
- **THEN** `notify_interventions` SHALL be false and no notifications are sent

### Requirement: Target safety margin
The balancer SHALL steer every phase a balanced load draws on toward `target_margin_percent` of `main_fuse_a` (default 85 %), not toward 100 %. It SHALL NOT raise any setpoint, restore any shed load, or return a charger from 1-phase to 3-phase if doing so would push a phase's projected averaged current (see "Asymmetric ramping with resume margin") above that target. It SHALL NOT resume a paused charger at a current that would push a phase's momentary current above that target (see "Pause below minimum current with anti-flap resume"). The target SHALL NOT itself trigger a reduction: a phase between the target and `main_fuse_a` holds its current setpoints. Reductions SHALL continue to be triggered only by negative headroom against `main_fuse_a`.

#### Scenario: Quiet night leaves room for full charging
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, the house draws 2 A per phase, and the planner target is 10 A
- **THEN** the balancer SHALL ramp the charger to 10 A (projected 12 A ≤ 13.6 A)

#### Scenario: Ramp-up stops at the target, not at the fuse
- **WHEN** `main_fuse_a` is 16 A, `target_margin_percent` is 85, and the averaged L1 current with the charger at 8 A is 13 A
- **THEN** the balancer SHALL NOT raise the setpoint to 9 A (projected 14 A > 13.6 A)
- **AND** it SHALL NOT reduce the setpoint either, because L1 is below `main_fuse_a`

### Requirement: 1-phase relief step in the degradation ladder
For a `type: current` charger with phase switching enabled, a configured `phase_mode_entity` and a non-failed phase controller, the balancer SHALL degrade in this order when a phase it draws on is overloaded:
1. Reduce the ampere setpoint immediately (the existing throttle).
2. If the setpoint is at `min_current_a`, the charger is in 3-phase mode, and every overloaded phase is one that 1-phase mode does not use (per `phase_1_line`), request 1-phase mode from the phase controller.
3. Pause (see "Pause below minimum current with anti-flap resume").

A 1-phase relief request SHALL bypass the power-threshold hysteresis of the phase state machine, but SHALL still respect `phase_switch_min_dwell_s` and the phase-mode fail-safe. When step 2 is not possible, the balancer SHALL proceed directly to step 3. These cases include: dwell not yet elapsed; the 1-phase line itself overloaded; phase switching disabled or failed; or a `type: binary` charger. While a relief request is outstanding, the charger SHALL be held at `min_current_a` rather than paused, unless the severe-overload rule applies. Chargers without phase switching SHALL behave exactly as before this requirement.

#### Scenario: Floor heating on L3 moves the car to L1
- **WHEN** the charger runs 3-phase at 6 A with `phase_1_line: 1`, L3 headroom falls to −4 A for longer than `pause_debounce_s`, L1 has headroom for 6 A more, and the last phase change was more than `phase_switch_min_dwell_s` ago
- **THEN** the balancer SHALL request 1-phase mode instead of pausing
- **AND** charging SHALL continue on L1

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
