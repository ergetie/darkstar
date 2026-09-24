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

Give-way ordering across ALL balanced loads SHALL be governed by the single ordered list `load_balancing.give_way_order` (see the `load-balancing-settings` capability): the balancer SHALL process entries top-down, and an entry SHALL only be asked to give way once every entry above it that draws on the overloaded phase(s) is exhausted (a charger entry is exhausted when paused; a shed entry when shed). A charger entry gives way by immediate setpoint reduction toward its `min_current_a`. When multiple entries could give way in the same tick, list position — not device kind — SHALL decide the order. A household whose order matches the migrated default (all current-type chargers before all shed loads) SHALL behave exactly as the previous two-tier system, and a household with a single dynamically-throttled charger and no shed loads SHALL behave exactly as before this requirement was introduced.

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
- **AND** charger A's setpoint SHALL only be reduced if the deficit persists after the water heater is shed

#### Scenario: Single dynamically-throttled charger is unaffected by ordering
- **WHEN** only one `type: current` EV charger is configured and no shed loads exist
- **THEN** its position in `give_way_order` SHALL have no observable effect on balancer behavior

### Requirement: Asymmetric ramping with resume margin
Setpoint decreases SHALL be applied immediately and without rate limit. Setpoint increases SHALL be rate-limited to `increase_step_a` per tick (default 1 A) and SHALL only occur when every phase the load draws on is below `resume_margin_percent` of `main_fuse_a` (default 90%).

#### Scenario: Load hovers just under the fuse limit
- **WHEN** L1 current sits at 95% of `main_fuse_a` with `resume_margin_percent: 90`
- **THEN** the balancer SHALL NOT increase the EV setpoint
- **AND** charging continues at the current reduced level

#### Scenario: Headroom recovers
- **WHEN** all phases drop below the resume margin and remain there
- **THEN** the balancer SHALL raise the setpoint by at most `increase_step_a` per tick until the planner-derived target is reached

### Requirement: Pause below minimum current with anti-flap resume
When a charger is at its minimum current (`min_current_a`, default 6 A) and it is the frontmost non-exhausted `give_way_order` entry on a phase that remains overloaded, the balancer SHALL pause charging (setpoint to minimum then stop). Equally, when the binding headroom cannot sustain even the minimum current and no entry above the charger can still give way, the balancer SHALL pause it. Charging SHALL resume only after both (a) `resume_delay_s` (default 120 s) has elapsed since the pause and (b) headroom for the minimum current exists with the resume margin satisfied.

#### Scenario: Heavy load forces a pause
- **WHEN** available headroom on a phase the EV uses falls below 6 A worth of charging and no higher-listed entry can give way
- **THEN** the balancer SHALL stop the charging session

#### Scenario: Brief dip does not cause rapid restart cycling
- **WHEN** charging was paused 30 s ago and headroom momentarily recovers
- **THEN** charging SHALL NOT resume until 120 s have elapsed and the margin condition holds

#### Scenario: Charger is not paused while a higher-listed shed load can still give way
- **WHEN** charger A is at its floor, the phase remains overloaded, and a shed entry listed above charger A on that phase has not yet been shed
- **THEN** the balancer SHALL shed that load before pausing charger A

### Requirement: Prioritized shedding and reverse-order restore of on/off loads
A shed entry in `give_way_order` SHALL give way by switching its load off once every entry above it drawing on the overloaded phase(s) is exhausted, per the top-down processing defined in "EV charger is throttled first using per-phase feedback". Shedding a water heater SHALL use its existing minimum-target actuation; shedding a custom entity SHALL write its configured off value; shedding a `type: binary` EV charger SHALL turn off its switch entity. A `type: current` EV charger SHALL NOT appear as a shed entry — it participates exclusively as a charger (throttle/pause) entry. Restore SHALL happen in exact reverse `give_way_order` (the last entry to give way is restored first), subject to the same resume delay and margin rules, across chargers and shed loads alike.

#### Scenario: EV at floor is not enough
- **WHEN** every entry above the water heater in `give_way_order` is exhausted and L2 remains over `main_fuse_a`
- **AND** the water heater (declared on L2) is heating
- **THEN** the balancer SHALL shed the water heater

#### Scenario: Restore order is reverse of give-way order
- **WHEN** two entries gave way (the higher-listed first, then the lower-listed) and headroom recovers durably
- **THEN** the lower-listed entry SHALL be restored before the higher-listed entry
- **AND** each restore SHALL wait for its own resume delay and margin conditions

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
When `load_balancing.notify_interventions` is true, the balancer SHALL send a user notification through the existing notification path (Home Assistant notify service with Discord webhook fallback) on these state transitions only: a load is shed, a charger is paused, and the stale-sensor fail-safe engages. Routine throttle adjustments and ramp-ups SHALL NOT notify. Each qualifying transition SHALL produce at most one notification (no per-tick repeats), carrying the same human-readable reason as its execution-log record. The default for `notify_interventions` SHALL be false.

#### Scenario: Water heater is shed overnight
- **WHEN** `notify_interventions` is true and the balancer sheds the water heater because L2 stayed over the fuse with all higher-listed entries exhausted
- **THEN** one notification SHALL be sent naming the water heater and the reason

#### Scenario: Routine throttling does not notify
- **WHEN** the balancer reduces a charger from 16 A to 12 A and later ramps it back
- **THEN** no notification SHALL be sent

#### Scenario: Feature defaults off
- **WHEN** a user upgrades without touching config
- **THEN** `notify_interventions` SHALL be false and no notifications are sent
