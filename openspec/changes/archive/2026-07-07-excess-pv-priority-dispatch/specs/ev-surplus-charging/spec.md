## ADDED Requirements

### Requirement: Solver plans EV surplus charging as a continuous variable

For each plugged-in EV charger of `type: current` that has an `ev` entry in `excess_pv.priority[]`, the Kepler solver SHALL create a continuous variable `ev_surplus_kw[d][t]` in `[0, charger max power]` per slot. The variable SHALL be constrained to 0 unless the pre-calculated excess-PV flag is true AND projected battery SoC >= `soc_threshold_percent` (same gating as existing sinks). Its consumption SHALL be added to the energy-balance demand side, and it SHALL earn the sink's rank-scaled reward in the objective.

#### Scenario: Surplus charging planned when battery is full and PV exceeds demand
- **WHEN** slot 40 has the excess-PV flag true and projected SoC is 96% with threshold 95%
- **AND** a plugged-in current-type charger has an `ev` entry in the priority list
- **THEN** the solver MAY set `ev_surplus_kw > 0` for that charger in slot 40, up to the charger's maximum power

#### Scenario: No surplus charging while battery is below threshold
- **WHEN** slot 20 has the excess-PV flag true but projected SoC is 80% with threshold 95%
- **THEN** `ev_surplus_kw` SHALL be 0 for slot 20 and the surplus SHALL charge the battery

#### Scenario: Unplugged charger gets no surplus variables
- **WHEN** the charger's `plugged_in` state is false at planning time
- **THEN** no `ev_surplus_kw` variables SHALL be created for it

#### Scenario: Binary-type charger is not a surplus sink
- **WHEN** an `ev` priority entry references a charger with `type: binary`
- **THEN** config validation SHALL reject the entry with an actionable error stating that surplus charging requires a `type: current` charger
- **AND** the solver SHALL create no surplus variables for a binary-type charger regardless (defense in depth if such a config bypasses validation)

### Requirement: Surplus charging and price-based scheduled charging are mutually exclusive per slot

A slot SHALL NOT have both `ev_charge[d][t] = 1` (scheduled charging) and `ev_surplus_kw[d][t] > 0` for the same charger. The solver SHALL enforce this exclusivity so planned EV energy is never double-counted.

#### Scenario: Cheap-hour slot uses scheduled charging only
- **WHEN** the solver selects slot 10 for price-based charging (`ev_charge = 1`)
- **THEN** `ev_surplus_kw` SHALL be 0 in slot 10 for that charger

#### Scenario: Surplus slot uses surplus charging only
- **WHEN** the solver sets `ev_surplus_kw > 0` in slot 44
- **THEN** `ev_charge` SHALL be 0 in slot 44 for that charger

### Requirement: Schedule output carries per-slot EV surplus eligibility

The schedule output SHALL include a per-slot `ev_surplus_kw` mapping (charger id → planned surplus kW) whenever any charger has planned surplus in that slot. Slots without surplus SHALL omit the field or carry zero. This field marks the slot as surplus-eligible for the executor.

#### Scenario: Surplus slot in schedule output
- **WHEN** the solver plans 3.2 kW of surplus charging for charger `goe` in slot 44
- **THEN** the slot output SHALL contain `ev_surplus_kw: {"goe": 3.2}`

#### Scenario: Existing consumers unaffected
- **WHEN** a schedule contains `ev_surplus_kw` fields
- **THEN** existing schedule consumers that do not know the field SHALL continue to work (field is additive)

### Requirement: Executor tracks measured surplus in real time during surplus-eligible slots

During a slot marked surplus-eligible for a charger, the executor SHALL each tick derive the live surplus from `SystemState` (export power for dual grid meters; negative grid power for net meters) and adjust the charger's ampere setpoint by feedback: raise the setpoint (subject to the increase-slow ramp from load balancing) while export exceeds a configurable deadband (default 0.2 kW), and lower it immediately while import exceeds the deadband. The planner's `ev_surplus_kw` value SHALL be treated as eligibility, not as an open-loop target.

#### Scenario: Setpoint rises while exporting
- **WHEN** the slot is surplus-eligible and measured export is 2.5 kW with a 0.2 kW deadband
- **THEN** the executor SHALL raise the EV ampere setpoint toward absorbing the export, honoring the ramp-rate limit

#### Scenario: Setpoint drops when a cloud removes the surplus
- **WHEN** the EV is surplus-charging and measured grid import rises to 1.5 kW
- **THEN** the executor SHALL lower the ampere setpoint on the same tick without ramp-rate limitation

#### Scenario: Stable within deadband
- **WHEN** measured grid exchange is within ±0.2 kW of zero
- **THEN** the executor SHALL keep the current setpoint unchanged

#### Scenario: Non-eligible slots behave as scheduled charging
- **WHEN** the current slot has no `ev_surplus_kw` entry for the charger
- **THEN** EV control SHALL follow the normal scheduled-charging behavior with no surplus feedback

### Requirement: Load-balancer cap is authoritative over surplus tracking

The fuse balancer's per-phase cap SHALL be applied after the surplus feedback computes its desired setpoint. The dispatched setpoint SHALL never exceed the balancer's cap, regardless of available surplus.

#### Scenario: Surplus wants more than the fuse allows
- **WHEN** surplus feedback computes 14 A but the balancer cap for the constrained phase allows 10 A
- **THEN** the executor SHALL dispatch 10 A

### Requirement: Sustained surplus shortfall pauses charging via the shared pause machinery

When the surplus feedback pushes the setpoint below the effective minimum (6 A × active phases) and phase switching cannot reduce the minimum further, the executor SHALL pause surplus charging using the shared pause primitive from load balancing. Resume SHALL require both the shared resume delay and measured surplus at or above the 1-phase minimum plus margin for the full delay period.

#### Scenario: Pause on sustained shortfall
- **WHEN** measured surplus stays below the effective minimum while already in the lowest-minimum phase mode
- **THEN** the executor SHALL pause charging rather than draw grid power

#### Scenario: No flapping on brief surplus return
- **WHEN** charging is paused and surplus exceeds the resume threshold for less than the resume delay
- **THEN** charging SHALL NOT resume yet

#### Scenario: Resume after stable surplus
- **WHEN** charging is paused and measured surplus stays above the 1-phase minimum plus margin for the full resume delay
- **THEN** the executor SHALL resume surplus charging at the minimum setpoint and ramp up per the feedback loop

### Requirement: EV source isolation is preserved during surplus charging

Surplus charging SHALL NOT cause the house battery to discharge into the EV. The existing EV source-isolation behavior (forcing battery discharge to zero while the EV charges) SHALL apply to surplus charging identically to scheduled charging.

#### Scenario: Battery stays idle while EV surplus-charges
- **WHEN** the EV is surplus-charging and the battery is at 100% SoC
- **THEN** the executor SHALL keep battery discharge at 0 kW
