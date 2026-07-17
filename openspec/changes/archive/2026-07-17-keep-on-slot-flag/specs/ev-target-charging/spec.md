## MODIFIED Requirements

### Requirement: Keep charger on after target
A per-charger `keep_on_after_target` (default false) SHALL, when true, keep the charger's intended switch state ON through the ready-by time after the target is met, so the vehicle can pre-condition / run its heater.

Keep-on intent SHALL be represented in the published schedule as an explicit per-slot, per-charger flag (`ev_keep_on: {charger_id: true}`), NOT as planned charging power: keep-on slots SHALL carry `0` in `ev_chargers[charger_id]` / contribute `0` to `ev_charging_kw` unless the solver genuinely planned charging energy for that slot. Published schedules SHALL therefore be energy-consistent — summing planned EV power across slots SHALL NOT include phantom keep-on energy that has no matching `grid_import_kwh`/`cost_sek`.

#### Scenario: Keep-on enabled
- **WHEN** the target is met before the ready-by time and `keep_on_after_target` is true
- **THEN** the plan SHALL keep the charger switch ON until the ready-by time
- **AND** no additional charging energy SHALL be required (the vehicle draws what it needs)

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
