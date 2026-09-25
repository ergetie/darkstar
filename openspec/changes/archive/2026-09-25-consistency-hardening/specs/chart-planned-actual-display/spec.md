## MODIFIED Requirements

### Requirement: Planned values sourced from slot_plans database

The backend SHALL provide planned values from the `slot_plans` table for all historical slots via the `battery_charge_kw`, `battery_discharge_kw`, `water_heating_kw`, `ev_charging_kw`, and `soc_target_percent` fields in the schedule API response. Energy-to-power conversion SHALL use each row's real slot duration from `slot_plans.slot_end`. Rows without a valid `slot_end` SHALL be treated as 15-minute slots.

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

#### Scenario: 60-minute slot
- **WHEN** a `slot_plans` row has `planned_ev_charging_kwh=11.0` and a `slot_end` one hour after `slot_start`
- **THEN** the API SHALL return `ev_charging_kw` 11.0

#### Scenario: Row without slot_end
- **WHEN** a `slot_plans` row has `planned_water_heating_kwh=0.5` and `slot_end` NULL
- **THEN** the API SHALL return `water_heating_kw` 2.0

### Requirement: slot_plans stores planned EV charging energy
The `slot_plans` table SHALL have a nullable `planned_ev_charging_kwh` column, added by an Alembic migration that runs on startup for every install. `store_plan` SHALL persist the aggregate planned EV energy for each slot it writes, converting from kW with the slot's real duration.

#### Scenario: Migration on an existing database
- **WHEN** an install with existing `slot_plans` rows starts with the new version
- **THEN** the column SHALL be added, existing rows SHALL have NULL, and no other data SHALL change

#### Scenario: Plan stored
- **WHEN** a plan with `ev_charging_kw=11.0` for a 15-minute slot is stored
- **THEN** that slot's `planned_ev_charging_kwh` SHALL be 2.75

#### Scenario: Plan stored with 30-minute slots
- **WHEN** a plan with `ev_charging_kw=11.0` and `water_heating_kw=3.0` for a 30-minute slot is stored
- **THEN** that slot's `planned_ev_charging_kwh` SHALL be 5.5 and `planned_water_heating_kwh` SHALL be 1.5

## ADDED Requirements

### Requirement: slot_plans stores each slot's end
The `slot_plans` table SHALL have a nullable `slot_end` column, added by an idempotent Alembic migration that runs on startup. `store_plan` SHALL write each slot's end, taken from the plan's `end_time`, in the same local ISO format as `slot_start`, and SHALL update it on upsert. A plan row whose end is missing or not after its start SHALL be stored with `slot_end` NULL, converted as a 15-minute slot, and logged as a warning.

#### Scenario: Migration on an existing database
- **WHEN** an install with existing `slot_plans` rows starts with the new version
- **THEN** `slot_end` SHALL be added, existing rows SHALL have NULL, and no other data SHALL change

#### Scenario: End stored
- **WHEN** a plan slot starting 10:00 and ending 10:15 is stored
- **THEN** that row's `slot_end` SHALL be 10:15 local time with offset

#### Scenario: Invalid end
- **WHEN** a plan row has `end_time` equal to its `start_time`
- **THEN** `slot_end` SHALL be NULL, planned kWh SHALL use a 15-minute duration, and a warning SHALL be logged

### Requirement: Observed history uses the real slot duration
The schedule API SHALL convert observed water energy (`slot_observations.water_kwh`) to `actual_water_kw` using each observation's duration from `slot_observations.slot_end`. Rows without a valid `slot_end` SHALL be treated as 15-minute slots.

#### Scenario: 30-minute observation
- **WHEN** an observation has `water_kwh=1.5` and a `slot_end` 30 minutes after `slot_start`
- **THEN** the API SHALL return `actual_water_kw` 3.0
