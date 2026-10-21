## ADDED Requirements

### Requirement: Coordinated increases with a pending-increase ledger
Every granted increase (EV, battery, shed, custom; ramp, plan step-up, resume or restore) SHALL be counted immediately in a cross-tick ledger of amperes per phase. Every increase SHALL pass one room gate with a single shared budget: averaged current plus pending increases plus the new one within `target_margin_percent` of `main_fuse_a`. Items expire when the measured value settles or after `pending_timeout_s`; a reduction clears them.


#### Scenario: EV and battery do not ramp together
- **WHEN** the EV and the battery both want to increase on the same tick and the shared room only fits one step
- **THEN** exactly one entry SHALL receive the step, in `give_way_order` priority (frontmost gives way first, so the rearmost is restored first)
- **AND** the other SHALL wait until the first item has settled or expired

#### Scenario: Lagging average does not hide a granted step
- **WHEN** a 600 W battery step was granted on the previous tick and the 60 s averaged current does not yet show it
- **THEN** the next tick's room gate SHALL still subtract that 600 W (as amperes per phase) from the room

#### Scenario: Plan step-up is gated
- **WHEN** the plan rises from 3000 W to 6000 W while the battery cap equals the plan
- **THEN** the battery cap SHALL rise by at most one granted step per gate pass, never in one write

#### Scenario: Spending in the same tick is counted
- **WHEN** a battery resume, a plan jump or a shed restore is granted in a tick
- **THEN** its amperes SHALL be deducted from the room available to later entries in the same tick

### Requirement: Shed-load restore is gated by the load's power
A shed load SHALL be restored only when the shared room fits that load's power on each of its phases. The power SHALL be taken, in order, from the live power sensor of the load, the configured `power_kw` (or `rated_power_kw` for a binary charger), and otherwise a worst-case fallback that counts the load as a full `main_fuse_a` on its phases (so it restores only when the whole phase is free). `ShedLoadInput` SHALL carry the resolved power and its source.

#### Scenario: Heater restore needs room for its power
- **WHEN** a 3.1 kW heater on L1 is shed and L1 has 6 A of room at 230 V
- **THEN** the heater SHALL NOT be restored until L1 has about 13.5 A of room (3.1 kW / 230 V)

#### Scenario: Unknown power uses worst case
- **WHEN** a custom load has no power sensor and no configured power
- **THEN** it SHALL be restored only when its phases have room for a full `main_fuse_a`, and the status SHALL report the fallback

#### Scenario: Restore does not oscillate
- **WHEN** a shed-and-restore sequence for a heater, EV and battery is simulated for ten minutes with a steady house load
- **THEN** the heater SHALL NOT toggle more often than its minimum off time allows and no phase SHALL exceed `main_fuse_a` for longer than one sensor interval

### Requirement: Shed respects the entries above it
A shed load SHALL give way only after every entry above it in `give_way_order` has had its chance, including a charger pause debounce (`pause_debounce_s`, or the successor defined by the proportional overload timing change). A negative pool headroom SHALL NOT shed a load while an entry above it is merely waiting out its debounce.

#### Scenario: Charger debounce pending
- **WHEN** a charger above the heater is at its minimum current, pause debounce is running and the pool headroom is negative
- **THEN** the heater SHALL NOT be shed before that debounce elapses unless the overload is severe per the existing immediate-pause rule

### Requirement: Reductions act once per fresh phase sample
The balancer SHALL detect each phase sensor's update cadence from sensor timestamps and act at most once per fresh sample. The first cut on a fresh overloaded sample SHALL be immediate. A further cut on that phase SHALL wait for the actuator's measured response, counting the ordered relief in the pool, for at most two detected sensor intervals (capped at 15 s).


#### Scenario: Duplicate reading
- **WHEN** two consecutive ticks see the same L1 sample
- **THEN** the second tick SHALL NOT reduce again

#### Scenario: Cut not yet reflected
- **WHEN** the battery was cut 5 s ago and the measured charge still shows the old value
- **THEN** further cuts SHALL wait for the response or the response timeout (two sensor intervals, at most 15 s), and the cut already made SHALL count as relief in the pool

#### Scenario: Overload persists after the response timeout
- **WHEN** a phase is still over `main_fuse_a` on a fresh sample after the response timeout
- **THEN** the balancer SHALL cut again immediately

### Requirement: Battery cut does not depend on measured charge catching up
The battery's reducible amount SHALL be derived from the current cap and grid import (not limited by a measured charge that lags the cap). Measured battery power MAY be used to detect response and to avoid cutting below what the battery really draws, but a measured charge of zero while the cap is higher SHALL NOT block a cut.

#### Scenario: Lagging charge measurement
- **WHEN** the cap is 6 kW, import is 12 kW and the measured charge is still 1 kW because the inverter is ramping
- **THEN** an overload on a phase SHALL still reduce the cap

### Requirement: Battery resume uses escalating back-off and a target margin
A paused battery SHALL resume only after its phases fit the minimum charge for a confirm time that escalates with repeated flaps in the same way as the EV charger (10 s, 30 s, 120 s steps, reset after a stable period). The battery SHALL resume at the minimum charge value (or at most the share of room within `target_margin_percent`), never at the full momentary whole-ampere headroom, and then ramp through the normal gate.

#### Scenario: Flapping battery
- **WHEN** the battery pauses and resumes three times within two minutes
- **THEN** the third confirm time SHALL be longer than the first

#### Scenario: Resume amount
- **WHEN** the battery resumes with 12 A of per-phase headroom
- **THEN** the resume cap SHALL be the minimum charge value and the remaining room SHALL be reached by gated ramp steps

### Requirement: Anti-wear adaptive step pacing
Each actuator (inverter charge power, EV current) SHALL take its next increase step once its previous step has settled in the measured value, or after `max_step_interval_s` (default 30 s), whichever comes first. Changes below `write_deadband_percent` (never below one profile step) SHALL NOT be written. Overload reductions SHALL bypass pacing and deadband.


#### Scenario: Fast actuator ramps at its own pace
- **WHEN** an actuator's measured value reaches each granted step within 8 s
- **THEN** the next step SHALL be allowed as soon as the previous step has settled, without waiting `max_step_interval_s`

#### Scenario: Slow or unmeasurable actuator
- **WHEN** the previous step has not settled or the actuator has no measured value
- **THEN** the next increase SHALL wait until `max_step_interval_s` has elapsed

#### Scenario: No churn
- **WHEN** a plan or room fluctuates by one step every five seconds
- **THEN** each actuator SHALL write at most one increase per settled step or `max_step_interval_s`, and changes below the deadband SHALL NOT be written

#### Scenario: Overload cut ignores the interval
- **WHEN** a phase is over the fuse limit and the last write was one second ago
- **THEN** the cut SHALL be written immediately

### Requirement: On/off load minimum on and off times
Water heaters and custom switches SHALL respect `min_on_s` and `min_off_s` (default 300 s) for restores and plan switching. An overload shed SHALL stay immediate.

#### Scenario: Water heater minimum off time
- **WHEN** a heater was shed for overload 60 s ago and room is available
- **THEN** it SHALL NOT be restored before `min_off_s` has elapsed

### Requirement: Reduction triggering is pluggable
The decision that a phase needs relief (overload detection) SHALL be isolated behind a single trigger function consumed by all reduction paths, returning for each phase the amount and urgency of required relief. This change SHALL keep the existing instant-threshold trigger. The proportional overload timing change MAY replace the trigger without changing the ledger, the room gate or the give-way ladder.

#### Scenario: Trigger swapped
- **WHEN** a different trigger function is supplied
- **THEN** reductions, ledger, restore gates and write limits SHALL behave unchanged apart from when a reduction starts

### Requirement: Battery power conversion uses measured voltage
Conversion between battery watts and phase amperes SHALL use the measured grid voltage of the battery's phases when `input_sensors.grid_voltage_l1/l2/l3` are configured and fresh, and `load_balancing.nominal_voltage_v` otherwise. A stale configured voltage SHALL follow the existing voltage staleness rule.

#### Scenario: Measured voltage
- **WHEN** L1 voltage is 236 V and nominal is 220 V
- **THEN** a 1 A phase reduction SHALL convert using 236 V on L1

### Requirement: Phase readings follow a sign convention
Per-phase readings SHALL NOT be passed through an absolute value. `load_balancing.phase_sign` (`import_positive` by default, or `import_negative`) SHALL define which sign means import. After applying it, a negative value (export) SHALL count as 0 A of load for that phase.

#### Scenario: Export phase
- **WHEN** L2 reads -5 A with `import_positive`
- **THEN** L2 SHALL be treated as 0 A

#### Scenario: Inverted sensor
- **WHEN** `phase_sign` is `import_negative` and L1 reads -12 A
- **THEN** L1 SHALL be treated as 12 A

### Requirement: Balancer decisions are logged and traced
The balancer SHALL log every decision change at INFO (entry, old and new value, reason) and not unchanged ticks. It SHALL keep a bounded ring buffer (default 600 ticks) of snapshots with raw and averaged per-phase currents and sensor ages, per-entry setpoint, plan, cap and reason, shed set, measured battery power, ledger and written values, available to the diagnostics bundle.


#### Scenario: Transition logged once
- **WHEN** the battery changes from `throttling` to `paused`
- **THEN** exactly one log line with entry, values and reason SHALL be emitted

#### Scenario: Buffer bound
- **WHEN** more ticks than the buffer size have run
- **THEN** only the newest snapshots SHALL be kept

## MODIFIED Requirements

### Requirement: Asymmetric ramping with resume margin
Setpoint decreases SHALL be applied immediately, without rate limit, and SHALL be computed from the momentary per-phase reading of the current tick. Setpoint increases SHALL be rate-limited to `increase_step_a` per granted step (default 1 A) and SHALL go through the shared pending-increase ledger and the minimum write interval (see "Coordinated increases with a pending-increase ledger" and "Anti-wear minimum write interval"). They SHALL be computed from a rolling average of each phase's current over `ramp_up_window_s` (default 60 s).

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

#### Scenario: Setpoint increases gated by target margin
- **WHEN** the balancer considers a setpoint increase
- **THEN** it SHALL only occur when, for every phase the load draws on, the averaged current plus the increase stays at or below `target_margin_percent` of `main_fuse_a` (see "Target safety margin")
- **AND** an increase SHALL also never exceed the phase's momentary headroom against `main_fuse_a` on the current tick

#### Scenario: Restores use the averaged reading
- **WHEN** a shed load is restored or a charger returns from 1-phase to 3-phase
- **THEN** the same averaged reading and target SHALL be used
- **AND** resuming a paused charger follows "Pause below minimum current with anti-flap resume"

#### Scenario: No increases without fresh averaging samples
- **WHEN** a phase does not yet have `ramp_up_window_s` of fresh samples (e.g. after startup or a stale-sensor episode)
- **THEN** increases on that phase SHALL NOT occur

### Requirement: Battery charge ramps back after relief
After a reduction the balancer SHALL NOT raise the battery cap for `ramp_up_window_s`. Later raises, including raises toward a higher plan, SHALL be `increase_step_a` per phase per granted step through the same room gate as every other increase, only while each battery phase's averaged current plus the raise stays within `target_margin_percent` of `main_fuse_a`, and never above the plan. A plan step-up SHALL NOT bypass this gate. A paused battery SHALL restore in reverse list order and resume per "Battery resume uses escalating back-off and a target margin".

#### Scenario: Relief after the washing machine stops
- **WHEN** the battery was throttled and the averaged L1 current has dropped well below the target margin for longer than `ramp_up_window_s`
- **THEN** the cap SHALL rise stepwise toward the plan and never exceed it

#### Scenario: Paused battery blocks restores above it
- **WHEN** the battery is paused and a shed load listed above it is shed
- **THEN** the shed load SHALL NOT be restored before the battery resumes

### Requirement: Battery entry under stale phase sensors
When any phase the battery draws on is stale, the balancer SHALL apply the same fail-safe as for the EV charger: immediately reduce the battery grid-charge cap to the profile minimum charge value, and pause grid charging (idle) when staleness persists beyond `resume_delay_s`. Balancing decisions SHALL NOT be made from stale data as if fresh.

#### Scenario: Stale L1 while throttled
- **WHEN** the battery is capped at 6 kW and L1 becomes stale
- **THEN** the cap SHALL drop to the profile minimum charge value
- **AND** if L1 is still stale after `resume_delay_s`, grid charging SHALL pause until L1 is fresh again


## REMOVED Requirements

### Requirement: Sustained battery throttle triggers a replan
**Reason**: The balancer-triggered replan is removed entirely (plans respect fuse limits instead).
**Migration**: None; `replan_after_throttled_s` is dropped from the config.
