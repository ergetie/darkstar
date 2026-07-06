# Delta Spec: Phase Load Balancing (load-balancing-completion)

## MODIFIED Requirements

### Requirement: EV charger is throttled first using per-phase feedback
When any phase used by a charging EV has negative headroom, the balancer SHALL reduce that charger's ampere setpoint by at least the magnitude of the worst negative headroom, immediately in the same tick, clamped to the charger's minimum current. When headroom is positive, the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`.

Give-way ordering across ALL balanced loads SHALL be governed by the single ordered list `load_balancing.give_way_order` (see the `load-balancing-settings` capability): the balancer SHALL process entries top-down, and an entry SHALL only be asked to give way once every entry above it that draws on the overloaded phase(s) is exhausted (a charger entry is exhausted when paused; a shed entry when shed). A charger entry gives way by immediate setpoint reduction toward its `min_current_a`. When multiple entries could give way in the same tick, list position — not device kind — SHALL decide the order. A household whose order matches the migrated default (all current-type chargers before all shed loads) SHALL behave exactly as the previous two-tier system, and a household with a single dynamically-throttled charger and no shed loads SHALL behave exactly as before this requirement was introduced.

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

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

## ADDED Requirements

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
