# Spec: Phase Load Balancing

## ADDED Requirements

### Requirement: Per-phase headroom computation
When load balancing is enabled, the executor SHALL compute per-phase headroom on every tick as `main_fuse_a − measured_grid_current_a` for each of L1, L2, L3, using current magnitude (direction-independent). The binding headroom for a load SHALL be the minimum headroom across the phases that load draws on.

#### Scenario: Unbalanced house load limits one phase
- **WHEN** `main_fuse_a` is 20 and measured grid currents are L1=18 A, L2=5 A, L3=5 A
- **THEN** headroom SHALL be computed as L1=2 A, L2=15 A, L3=15 A
- **AND** the binding headroom for a 3-phase EV charger SHALL be 2 A

#### Scenario: Total power within limits but one phase over fuse
- **WHEN** total grid power is below `system.grid.max_power_kw` equivalents
- **AND** L1 measured current exceeds `main_fuse_a`
- **THEN** the balancer SHALL still act to reduce L1 loading (per-phase, not total-kW, governs)

### Requirement: EV charger is throttled first using per-phase feedback
When any phase used by a charging EV has negative headroom, the balancer SHALL reduce that charger's ampere setpoint by at least the magnitude of the worst negative headroom, immediately in the same tick, clamped to the charger's minimum current. When headroom is positive, the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`.

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

#### Scenario: Balancer never exceeds the planned charging level
- **WHEN** the planner-derived target for the current slot is 10 A and all phases have ample headroom
- **THEN** the balancer SHALL NOT raise the setpoint above 10 A

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
When the binding headroom cannot sustain the charger's minimum current (`min_current_a`, default 6 A), the balancer SHALL pause charging (setpoint to minimum then stop). Charging SHALL resume only after both (a) `resume_delay_s` (default 120 s) has elapsed since the pause and (b) headroom for the minimum current exists with the resume margin satisfied.

#### Scenario: Heavy load forces a pause
- **WHEN** available headroom on a phase the EV uses falls below 6 A worth of charging
- **THEN** the balancer SHALL stop the charging session

#### Scenario: Brief dip does not cause rapid restart cycling
- **WHEN** charging was paused 30 s ago and headroom momentarily recovers
- **THEN** charging SHALL NOT resume until 120 s have elapsed and the margin condition holds

### Requirement: Prioritized shedding and reverse-order restore of on/off loads
When the EV is already paused or at its floor and a phase remains over the fuse, the balancer SHALL shed configured on/off balanced loads declared on the overloaded phase(s), lowest priority first. Restore SHALL happen in reverse order, subject to the same resume delay and margin rules. Shedding a water heater SHALL use its existing minimum-target actuation; shedding a custom entity SHALL write its configured off value.

#### Scenario: EV at floor is not enough
- **WHEN** the EV is paused and L2 remains over `main_fuse_a`
- **AND** the water heater (declared on L2, priority 1) is heating
- **THEN** the balancer SHALL shed the water heater

#### Scenario: Restore order is reverse of shed order
- **WHEN** two loads were shed (priority 1 first, then priority 2) and headroom recovers durably
- **THEN** the priority-2 load SHALL be restored before the priority-1 load
- **AND** the EV resumes last only after margin and delay conditions hold

### Requirement: Stale sensor fail-safe
If any per-phase grid current value is missing or older than `sensor_stale_after_s` (default 30 s), the balancer SHALL immediately reduce the EV to `min_current_a`. If staleness persists beyond one resume cycle (`resume_delay_s`), the balancer SHALL pause charging. Balancing decisions SHALL never be made from stale data as if it were fresh.

#### Scenario: Phase sensor stops updating mid-charge
- **WHEN** the L1 sensor's last update is older than 30 s while the EV charges at 16 A
- **THEN** the balancer SHALL set the EV to 6 A
- **AND** if data is still stale 120 s later, charging SHALL be stopped

### Requirement: Feature gating
Load balancing SHALL run only when `load_balancing.enabled` is true and prerequisites are configured (fuse rating, per-phase sensors, at least one balanced load). When disabled or unconfigured, executor behavior SHALL be identical to the pre-change system, including binary EV control.

#### Scenario: User without per-phase sensors
- **WHEN** `load_balancing.enabled` is false
- **THEN** no balancer logic runs and scheduled EV charging operates as today

### Requirement: Execution log throttling at high tick frequency
The executor SHALL write an execution-log record only when the tick produced a change (mode intent, dispatched action, override or balancer state transition), plus a heartbeat record at least once per 15-minute slot. Every balancer state transition (throttle start/stop, shed, restore, pause, resume, stale-data fallback) SHALL be logged with a human-readable reason.

#### Scenario: Idle 5-second ticks do not flood the database
- **WHEN** the executor ticks every 5 s and nothing changes for a full slot
- **THEN** at most one heartbeat record SHALL be written for that slot

#### Scenario: Balancer intervention is always auditable
- **WHEN** the balancer reduces the EV from 16 A to 10 A because L1 headroom went negative
- **THEN** an execution-log record SHALL be written including the reason and per-phase currents
