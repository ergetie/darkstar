## MODIFIED Requirements

### Requirement: Planned values sourced from slot_plans database

The backend SHALL provide planned values from the `slot_plans` table for all historical slots via the `battery_charge_kw`, `battery_discharge_kw`, `water_heating_kw`, `ev_charging_kw`, and `soc_target_percent` fields in the schedule API response.

#### Scenario: Backend provides planned values for historical slots
- **WHEN** the schedule API returns historical slot data
- **THEN** the response SHALL include `battery_charge_kw` from `slot_plans.planned_charge_kwh`
- **AND** the response SHALL include `battery_discharge_kw` from `slot_plans.planned_discharge_kwh`
- **AND** the response SHALL include `water_heating_kw` from `slot_plans.planned_water_heating_kwh`
- **AND** the response SHALL include `ev_charging_kw` from `slot_plans.planned_ev_charging_kwh` when that value is not NULL

#### Scenario: Planned EV survives a replan
- **WHEN** a slot had planned EV charging, the slot has passed, and the planner has replanned (including after the EV goal is cleared)
- **THEN** the schedule API SHALL still return that slot's planned `ev_charging_kw`

#### Scenario: Rows from before the migration
- **WHEN** a historical slot's `planned_ev_charging_kwh` is NULL
- **THEN** the API SHALL NOT fabricate a planned EV value of zero from the database

## ADDED Requirements

### Requirement: slot_plans stores planned EV charging energy
The `slot_plans` table SHALL have a nullable `planned_ev_charging_kwh` column, added by an Alembic migration that runs on startup for every install. `store_plan` SHALL persist the aggregate planned EV energy for each slot it writes.

#### Scenario: Migration on an existing database
- **WHEN** an install with existing `slot_plans` rows starts with the new version
- **THEN** the column SHALL be added, existing rows SHALL have NULL, and no other data SHALL change

#### Scenario: Plan stored
- **WHEN** a plan with `ev_charging_kw=11.0` for a 15-minute slot is stored
- **THEN** that slot's `planned_ev_charging_kwh` SHALL be 2.75
