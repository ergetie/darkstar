## MODIFIED Requirements

### Requirement: Required energy is derived from target SoC
The pipeline SHALL compute `required_kwh = max(0, (target_soc_percent − resolved_soc_percent)/100 · battery_capacity_kwh)`, where the resolved SoC is defined by the `ev-soc-staleness` capability (`live` or `carried`). Energy already delivered SHALL NOT be subtracted when a resolved SoC is available, because the SoC already reflects delivered energy.

When a plugged charger has a SoC sensor configured but its resolved SoC status is `stale`, the pipeline SHALL NOT compute a required energy, and goal charging SHALL be suspended as specified in `ev-soc-staleness`. An unplugged charger with an active goal (assumed-plugged planning) SHALL use the resolved SoC, else its last persisted SoC regardless of age, and SHALL NOT be planned when neither exists.

Only when the charger has no SoC sensor configured at all SHALL the pipeline use the SoC-less estimate minus that charger's own delivered-today energy (per-charger, from the `ev-per-charger-energy` capability). When per-charger delivered energy is unknown, no subtraction SHALL be applied.

#### Scenario: Live SoC reflects progress — no double count
- **WHEN** the target implies 30 kWh at plug-in, 15 kWh has been delivered, and the live SoC now implies 15 kWh remaining
- **THEN** `required_kwh` SHALL be 15 (not 0)

#### Scenario: No SoC sensor configured
- **WHEN** a charger has no SoC sensor configured and 10 kWh has been delivered today by that charger
- **THEN** `required_kwh` SHALL be the SoC-less estimate minus 10, regardless of how many chargers are enabled

#### Scenario: SoC sensor configured but stale
- **WHEN** a plugged charger's SoC sensor has had no valid reading for longer than `soc_stale_after_minutes`
- **THEN** no `required_kwh` SHALL be computed and the solver SHALL receive no goal requirement for that charger

#### Scenario: Unplugged charger plans from the persisted SoC
- **WHEN** an unplugged charger with an active goal has no live or carried SoC and a persisted SoC of 70%
- **THEN** `required_kwh` SHALL be computed from 70% and the charger SHALL be planned as assumed plugged

#### Scenario: Target already met
- **WHEN** the resolved SoC already meets or exceeds `target_soc_percent`
- **THEN** `required_kwh` SHALL be 0 and no charging SHALL be scheduled (subject to keep-on behaviour)

### Requirement: Keep charger on after target
A per-charger `keep_on_after_target` (default false) SHALL, when true, keep the charger's intended switch state ON through the ready-by time once the resolved SoC (status `live` or `carried`) is at or above `target_soc_percent`, for any target value. This lets the vehicle pre-condition or run its heater.

Keep-on intent SHALL be represented in the published schedule as an explicit per-slot, per-charger flag (`ev_keep_on: {charger_id: true}`), NOT as planned charging power. Keep-on slots SHALL carry `0` in `ev_chargers[charger_id]`, and contribute `0` to `ev_charging_kw`, unless the solver genuinely planned charging energy for that slot. Published schedules SHALL therefore be energy-consistent: summing planned EV power across slots SHALL NOT include phantom keep-on energy that has no matching `grid_import_kwh`/`cost_sek`.

#### Scenario: Keep-on enabled
- **WHEN** the target is met before the ready-by time and `keep_on_after_target` is true
- **THEN** the plan SHALL keep the charger switch ON until the ready-by time
- **AND** no additional charging energy SHALL be required (the vehicle draws what it needs)

#### Scenario: Keep-on at a target below 100
- **WHEN** `target_soc_percent` is 80, the resolved SoC is 81%, and `keep_on_after_target` is true
- **THEN** keep-on flags SHALL be applied to slots up to the ready-by time

#### Scenario: Keep-on with stale SoC
- **WHEN** the resolved SoC status is `stale`
- **THEN** no keep-on flags SHALL be applied

#### Scenario: Keep-on disabled (default)
- **WHEN** the target is met and `keep_on_after_target` is false
- **THEN** the plan SHALL allow the charger switch to turn OFF once the target is met

#### Scenario: Keep-on slots carry flag, not fake power
- **WHEN** the planner applies keep-on-after-target to a future slot for charger `ev1`
- **THEN** the slot's serialized `ev_keep_on` dict SHALL contain `{"ev1": true}`
- **AND** the slot's `ev_chargers["ev1"]` SHALL be `0` (absent solver-planned charging)
- **AND** the slot's `ev_charging_kw` SHALL NOT include any keep-on contribution

#### Scenario: Schedule totals are energy-consistent under keep-on
- **WHEN** a schedule contains keep-on slots
- **THEN** summing `ev_charging_kw` across the schedule SHALL yield only genuinely planned charging energy
- **AND** no slot SHALL show EV charging power without corresponding energy-balance accounting

#### Scenario: Slots without keep-on are unchanged
- **WHEN** a slot has no charger in keep-on state
- **THEN** its `ev_keep_on` field SHALL be absent or an empty dict
- **AND** solver-planned `ev_chargers`/`ev_charging_kw` values SHALL be published exactly as solved

### Requirement: In-progress slot uses remaining time for EV energy
When planning starts inside a slot, the solver SHALL bound that slot's EV energy by the remaining duration (`slot_end − now`), not the full slot duration. This applies to both scheduled and surplus EV energy: the surplus reward, the surplus load in the energy balance, the excess-PV sink cap and the surplus energy counted toward the goal requirement SHALL all use the remaining duration. The planned EV kW for that slot SHALL be reported as energy divided by the remaining duration. Other energy flows in the slot SHALL be unchanged.

#### Scenario: Replan 7 minutes into a slot
- **WHEN** a replan runs at 10:22 for the 10:15–10:30 slot and the goal needs 1.2 kWh by 10:30
- **THEN** the solver SHALL allow at most `max_power_kw × 8/60` kWh in that slot
- **AND** the reported kW for that slot SHALL be the planned energy divided by 8/60 h

#### Scenario: Surplus in a partial first slot
- **WHEN** a replan runs 7 minutes into a surplus-eligible slot
- **THEN** that slot's surplus EV energy terms SHALL use the 8/60 h remaining duration

#### Scenario: Replan at slot start
- **WHEN** a replan runs exactly at a slot boundary
- **THEN** the EV bounds SHALL be identical to before this change
