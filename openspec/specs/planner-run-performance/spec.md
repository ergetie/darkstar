# Capability: Planner Run Performance

## Purpose

Keeps planner runs fast by batching forecast and plan persistence, reusing per-day sun times, and computing hybrid PV over the whole horizon at once, with results identical to the per-row/per-slot computation.

## Requirements

### Requirement: Batched Forecast Persistence

`LearningStore.store_forecasts` SHALL persist all rows of one call with a single batched upsert inside one transaction, and the persisted rows MUST be identical to upserting each row individually in input order.

#### Scenario: New forecast rows inserted
- **WHEN** `store_forecasts` is called with 672 rows for slots not yet stored
- **THEN** 672 rows SHALL exist for that `forecast_version` with the supplied values

#### Scenario: Existing rows updated
- **WHEN** `store_forecasts` is called with rows whose `(slot_start, forecast_version)` already exist
- **THEN** each stored row SHALL take the new values for every updated column

#### Scenario: NULL Open-Meteo value keeps stored value
- **WHEN** an incoming row has `openmeteo_pv_forecast_kwh` NULL and the stored row has a value
- **THEN** the stored `openmeteo_pv_forecast_kwh` SHALL be kept

#### Scenario: Rows without slot start skipped
- **WHEN** an incoming row has no `slot_start` or `start_time`
- **THEN** that row SHALL be skipped and the others persisted

#### Scenario: Duplicate slot in one call
- **WHEN** one call contains two rows with the same `slot_start`
- **THEN** the stored row SHALL hold the values of the later row

### Requirement: Batched Plan Persistence

`LearningStore.store_plan` SHALL persist all plan slots of one call with a single batched upsert inside one transaction, with the same derived values (energy scaling by real slot duration, `slot_end` handling, `created_at` refresh on update) as per-row persistence.

#### Scenario: Plan stored with derived energies
- **WHEN** `store_plan` is called with a plan whose slots are 15 minutes long
- **THEN** each stored `planned_water_heating_kwh` and `planned_ev_charging_kwh` SHALL equal the slot's kW value times 0.25

#### Scenario: Missing slot end
- **WHEN** a plan slot has no valid end time
- **THEN** its `slot_end` SHALL be stored as NULL, 15 minutes SHALL be assumed, and a warning SHALL be logged for that slot

### Requirement: Per-Day Sun Time Reuse

`SunCalculator` SHALL compute sunrise and sunset at most once per calendar date per instance, and `is_sun_up` MUST return the same result as computing them for every call.

#### Scenario: Many slots on one day
- **WHEN** `is_sun_up` is called for all 96 slots of one date
- **THEN** the astronomical calculation SHALL run once for that date

#### Scenario: Results unchanged
- **WHEN** `is_sun_up` is called for every 15-minute slot over 7 days with a 30-minute buffer
- **THEN** each result SHALL equal the uncached calculation

### Requirement: Whole-Horizon Hybrid PV Computation

Hybrid PV inference SHALL apply residual bounding, personalization weighting, the astro clamp, the radiation clamp (`< 1.0 W/m²`), the zero floor and the physical ceiling to the whole horizon at once, producing values identical to the per-slot computation.

#### Scenario: Identical hybrid PV output
- **WHEN** hybrid PV inference runs on a fixed 672-slot fixture with baseline, residual predictions, radiation and sun-up flags
- **THEN** every `pv_p10`, `pv_p50`, `pv_p90` and `ml_residual_*` value SHALL equal the per-slot computation

#### Scenario: NaN residual handled like the per-slot computation
- **WHEN** the ML residual prediction for a slot is NaN (optionally with NaN baseline or radiation elsewhere in the horizon)
- **THEN** the residual SHALL bound to `-max_residual` and any NaN value SHALL floor to 0.0, so every value equals the per-slot computation and no NaN is produced from a NaN residual

#### Scenario: Night and low radiation zeroed
- **WHEN** a slot is outside the sun-up window or its radiation is below 1.0 W/m²
- **THEN** its PV value before smoothing SHALL be 0.0
