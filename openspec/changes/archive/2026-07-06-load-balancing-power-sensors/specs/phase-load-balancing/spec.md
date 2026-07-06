## MODIFIED Requirements

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
When any phase used by a charging EV has negative headroom, the balancer SHALL reduce that charger's ampere setpoint by at least the magnitude of the worst negative headroom, immediately in the same tick, clamped to the charger's minimum current. When headroom is positive, the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`.

Every `type: current` EV charger SHALL be a member of the dynamically-throttled group and SHALL be assigned a priority (lower number gives way first). When multiple dynamically-throttled chargers share an overloaded phase in the same tick, the balancer SHALL process them in priority order: the lowest-priority charger SHALL be reduced fully to its `min_current_a` (or paused if headroom cannot sustain even that) before any headroom is allocated to the next-priority charger. A household with a single dynamically-throttled charger SHALL behave exactly as before this requirement was introduced (priority is a no-op with one charger).

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

#### Scenario: Balancer never exceeds the planned charging level
- **WHEN** the planner-derived target for the current slot is 10 A and all phases have ample headroom
- **THEN** the balancer SHALL NOT raise the setpoint above 10 A

#### Scenario: Two chargers share an overloaded phase, lower priority gives way first
- **WHEN** charger A (priority 1) and charger B (priority 2) both draw on L1, which has −10 A headroom
- **THEN** the balancer SHALL reduce charger A toward its floor first, using as much of the −10 A deficit as charger A's headroom down to `min_current_a` can absorb
- **AND** charger B SHALL only be reduced if charger A being fully at its floor is insufficient to resolve the remaining deficit

#### Scenario: Single dynamically-throttled charger is unaffected by priority
- **WHEN** only one `type: current` EV charger is configured
- **THEN** its priority value SHALL have no observable effect on balancer behavior

### Requirement: Prioritized shedding and reverse-order restore of on/off loads
When every dynamically-throttled EV charger is already paused or at its floor and a phase remains over the fuse, the balancer SHALL shed configured on/off balanced loads declared on the overloaded phase(s), lowest priority first. Restore SHALL happen in reverse order, subject to the same resume delay and margin rules. Shedding a water heater SHALL use its existing minimum-target actuation; shedding a custom entity SHALL write its configured off value; shedding a `type: binary` EV charger SHALL turn off its switch entity. A `type: current` EV charger SHALL NOT appear in this on/off shed list — it is exclusively managed by the dynamically-throttled group's continuous priority ordering (see "EV charger is throttled first using per-phase feedback").

#### Scenario: EV at floor is not enough
- **WHEN** every dynamically-throttled EV charger is paused or at floor and L2 remains over `main_fuse_a`
- **AND** the water heater (declared on L2, priority 1) is heating
- **THEN** the balancer SHALL shed the water heater

#### Scenario: Restore order is reverse of shed order
- **WHEN** two loads were shed (priority 1 first, then priority 2) and headroom recovers durably
- **THEN** the priority-2 load SHALL be restored before the priority-1 load
- **AND** dynamically-throttled chargers resume last only after margin and delay conditions hold

### Requirement: Stale sensor fail-safe
If any per-phase grid current value is missing or older than `sensor_stale_after_s` (default 30 s), the balancer SHALL immediately reduce the EV to `min_current_a`. If staleness persists beyond one resume cycle (`resume_delay_s`), the balancer SHALL pause charging. Balancing decisions SHALL never be made from stale data as if it were fresh.

For a phase in power-sensor mode with a configured voltage entity, "the per-phase grid current value" for staleness purposes SHALL be considered stale if either the power reading or the voltage reading is missing or older than `sensor_stale_after_s` — i.e., the fail-safe SHALL use the older of the two readings' timestamps. A phase with no voltage entity configured is not affected by this rule (it always uses the nominal fallback voltage, which has no staleness of its own).

#### Scenario: Phase sensor stops updating mid-charge
- **WHEN** the L1 sensor's last update is older than 30 s while the EV charges at 16 A
- **THEN** the balancer SHALL set the EV to 6 A
- **AND** if data is still stale 120 s later, charging SHALL be stopped

#### Scenario: Configured voltage entity goes stale
- **WHEN** L2 is in power-sensor mode with a configured voltage entity, the power reading is fresh, but the voltage entity's last update is older than `sensor_stale_after_s`
- **THEN** L2 SHALL be treated as stale by this fail-safe (same as a stale current/power reading)
- **AND** the balancer SHALL NOT substitute `load_balancing.nominal_voltage_v` in place of the stale voltage entity

#### Scenario: No voltage entity configured is not staleness
- **WHEN** L3 is in power-sensor mode with no voltage entity configured, and the power reading is fresh
- **THEN** L3 SHALL NOT be considered stale on account of having no voltage entity
- **AND** `load_balancing.nominal_voltage_v` SHALL be used for the conversion
