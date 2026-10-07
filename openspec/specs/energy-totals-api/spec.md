# Energy Totals API

## Purpose

API endpoints for retrieving aggregated energy totals from the database.
## Requirements
### Requirement: Energy endpoints query database for totals
The `/api/energy/today` and `/api/energy/range` endpoints SHALL query the database (SlotObservation table) to calculate energy totals, instead of reading Home Assistant sensors. These endpoints are served from `backend/api/routers/energy.py`.

#### Scenario: /energy/today returns DB-aggregated data
- **WHEN** a client calls GET /api/energy/today
- **THEN** the endpoint queries SlotObservation table for today's records
- **AND** returns aggregated totals: load_consumption_kwh, pv_production_kwh, grid_import_kwh, grid_export_kwh, battery_charge_kwh, battery_discharge_kwh, ev_charging_kwh

#### Scenario: /energy/range returns DB data for today
- **WHEN** a client calls GET /api/energy/range with period="today"
- **THEN** the endpoint queries SlotObservation table for today's records
- **AND** returns DB-aggregated data WITHOUT overlaying HA sensor values
- **AND** does NOT use the previous max(db_value, ha_value) logic

### Requirement: Energy endpoints include EV charging data
The energy endpoints SHALL include `ev_charging_kwh` in the response, representing the sum of EV charging energy for the requested period. These endpoints are served from `backend/api/routers/energy.py`.

#### Scenario: Response includes ev_charging_kwh
- **WHEN** a client calls any energy endpoint
- **THEN** the response includes an `ev_charging_kwh` field
- **AND** the value is the sum of `ev_charging_kwh` from SlotObservation records for the period
- **AND** the value is `0.0` if no EV charging occurred or no EV is configured

### Requirement: Energy endpoints return battery wear cost
The `/api/energy/today` and `/api/energy/range` endpoints SHALL return a `battery_wear_cost_sek` field representing the modelled battery degradation cost for the requested period. It SHALL be computed from data already aggregated by the endpoint as:

```
battery_wear_cost_sek = (battery_charge_kwh + battery_discharge_kwh) * battery_cycle_cost_kwh * 0.5
```

where `battery_cycle_cost_kwh` is read from `battery_economics.battery_cycle_cost_kwh` in configuration. The `* 0.5` factor mirrors the solver's wear model so a full charge+discharge cycle is charged the configured cost per kWh once. The value SHALL be non-negative and `0.0` when there is no battery throughput in the period.

The endpoints SHALL also return `net_cost_incl_wear_sek = net_cost_sek + battery_wear_cost_sek`, i.e. the net grid cost with battery wear added. The existing `net_cost_sek` field (pure grid import cost minus export revenue) SHALL be unchanged.

#### Scenario: Response includes battery wear cost
- **WHEN** a client calls GET /api/energy/today or /api/energy/range
- **THEN** the response includes `battery_wear_cost_sek` and `net_cost_incl_wear_sek`
- **AND** `battery_wear_cost_sek` equals `(battery_charge_kwh + battery_discharge_kwh) * battery_cycle_cost_kwh * 0.5`
- **AND** `net_cost_incl_wear_sek` equals `net_cost_sek + battery_wear_cost_sek`

#### Scenario: No battery activity yields zero wear
- **WHEN** the period has no battery charge or discharge
- **THEN** `battery_wear_cost_sek` is `0.0`
- **AND** `net_cost_incl_wear_sek` equals `net_cost_sek`

#### Scenario: Pure grid net cost is unaffected
- **WHEN** a client reads `net_cost_sek`
- **THEN** it still equals import cost minus export revenue, with no wear cost mixed in

### Requirement: Energy endpoints return source-attributed EV cost
`/api/energy/today` and `/api/energy/range` SHALL return `ev_grid_kwh`, `ev_solar_kwh`, `ev_cost_sek` and `ev_solar_share` for the period. They SHALL be computed per slot as defined by the `ev-cost-attribution` capability and summed from `slot_observations`. `ev_cost_sek` SHALL be the EV's grid import cost only and SHALL NOT exceed `import_cost_sek`.

The existing fields, including `ev_charging_kwh`, `import_cost_sek` and `net_cost_sek`, SHALL be unchanged. The zero-fallback response SHALL include the new fields, with 0 values and a null share.

#### Scenario: Fields present
- **WHEN** a client calls either endpoint for a period with EV charging
- **THEN** the response SHALL include the four EV cost fields
- **AND** `ev_grid_kwh + ev_solar_kwh` SHALL equal `ev_charging_kwh` within rounding

#### Scenario: Error fallback
- **WHEN** the aggregation fails and the zero fallback is returned
- **THEN** `ev_cost_sek` SHALL be 0 and `ev_solar_share` SHALL be null

### Requirement: Cost series endpoint returns cost per bucket and the running net
`GET /api/energy/cost-series` SHALL accept the same `period` (`today`, `yesterday`, `week`, `month`, `custom`) and `start_date`/`end_date` parameters as `/api/energy/range`, resolve them with the same shared period helper, and return cost per bucket from the SlotObservation table. For each slot the import cost SHALL be `import_kwh × import_price_sek_kwh` and the export revenue `export_kwh × export_price_sek_kwh`, the same pricing as `/api/energy/range`. Slots SHALL be bucketed by local hour when the range is a single day and by local day otherwise; the response `bucket` SHALL be `"hour"` or `"day"`.

Each point SHALL contain `start` (local ISO time of the bucket), `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` (import minus export) and `cumulative_net_cost_sek` (running sum over the points up to and including it). Points SHALL be ordered by time. Slots that have not started yet SHALL be excluded, even if the recorder holds rows for them. An invalid custom range (bad date format, or end before start) SHALL return an empty `points` list and an `error` message rather than failing.

#### Scenario: Hourly buckets and running net for one day
- **WHEN** a client calls GET /api/energy/cost-series?period=today and two started hours have import cost 8.0 and export revenue 1.0 in the second
- **THEN** `bucket` is "hour", there are two points, and the last point's `cumulative_net_cost_sek` equals the first hour's net plus the second hour's net

#### Scenario: Last cumulative value matches the range total
- **WHEN** a client calls both /api/energy/range and /api/energy/cost-series for the same period
- **THEN** the last point's `cumulative_net_cost_sek` equals the range response's `net_cost_sek`

#### Scenario: Longer period is bucketed by day
- **WHEN** a client calls GET /api/energy/cost-series?period=week
- **THEN** `bucket` is "day" and each point sums one local day

#### Scenario: Future slots are excluded
- **WHEN** the recorder holds rows for slots later today
- **THEN** those slots are not in the response

#### Scenario: Invalid custom range
- **WHEN** `period=custom` with an end date before the start date
- **THEN** the response has an empty `points` list and an `error` message

### Requirement: Cost series endpoint returns the without-Darkstar baseline
GET /api/energy/cost-series SHALL preserve its existing actual metered import_cost_sek, export_revenue_sek, net_cost_sek and cumulative_net_cost_sek fields and legacy baseline fields for compatibility. It SHALL add a separately named battery_comparison object for the comparison defined by no-darkstar-baseline and battery-comparison-calibration. Legacy baseline data SHALL NOT be represented as a validated or configured-loss comparison or used as a fallback for battery_comparison.

battery_comparison SHALL carry status, stable reason code, method_version, through, `coverage` and any real calibration diagnostics, including factors, training/validation windows, sample counts and validation errors. Status SHALL be one of available, estimated, insufficient_data, unreliable_model, incomplete_period, no_battery, or no_data. An available result SHALL have basis calibrated; an estimated result SHALL have basis configured_losses and preserve the actual calibration status/reason and only diagnostics from a real fit. Both amount-bearing statuses SHALL contain Darkstar and self-use summaries, each with grid_cost_sek, wear_cost_sek, stored_energy_change_kwh, stored_energy_value_sek and comparison_cost_sek, plus saving_sek, reference_price_sek_kwh and bucketed comparison points. Each point SHALL contain bucket start, darkstar_cumulative_comparison_cost_sek and self_use_cumulative_comparison_cost_sek. An estimated result SHALL be explicitly identified as an estimate and SHALL NOT imply calibration passed. For unavailable statuses, summaries, savings and comparison points SHALL be absent rather than zero-filled.

`coverage` SHALL be `{covered_slots, total_slots, excluded_slots}` for the selected period's completed slots, and SHALL also be present on unavailable responses (with covered_slots 0 when no usable run exists). The comparison is segmented per no-darkstar-baseline: invalid, unsupported or missing slots are excluded and counted in coverage instead of making the period unavailable, and the amounts, points and `through` describe the covered runs. An available (calibrated) result SHALL be returned only when excluded_slots is 0 and the slots form a single run; otherwise the amounts SHALL be a segmented estimate. Invalid or unsupported selected-period inputs SHALL NOT produce amounts for the excluded slots, and a period with no usable run SHALL be unavailable.

Comparison points SHALL cumulatively include modeled grid cost, wear and stored-energy valuation using the same period reference price at every boundary. Across runs, points SHALL be offset so the final endpoints equal the summed summary comparison costs, and saving SHALL equal their difference, within rounding; a bucket containing no covered slot SHALL have no point. Original cash-flow points SHALL retain original accounting and started-slot coverage; comparison points SHALL include only completed observations and valid required state-of-charge endpoints at each bucket boundary, subject to the estimate and calibration eligibility rules. Single-day comparisons SHALL bucket by local hour and longer comparisons by local day, retaining distinct UTC identities across DST.

#### Scenario: Baseline fields present with a battery
- **WHEN** a battery installation has recorded slots
- **THEN** existing legacy baseline fields retain compatibility
- **AND** the response independently reports whether battery_comparison is available, estimated or unavailable

#### Scenario: Last baseline cumulative matches the baseline total
- **WHEN** legacy baseline points or amount-bearing comparison points are returned
- **THEN** the final legacy cumulative continues to equal legacy baseline.net_cost_sek
- **AND** each comparison endpoint equals its respective active-basis summary

#### Scenario: Saving matches the definition
- **WHEN** self-use comparison cost is 40 kr and Darkstar comparison cost is 30 kr on either supported comparison basis
- **THEN** battery_comparison.saving_sek is 10 kr
- **AND** the difference between final comparison endpoints is 10 kr

#### Scenario: Stored-energy fields
- **WHEN** Darkstar retains 0.4 kWh more and the common reference price is 2.0 kr/kWh
- **THEN** the difference between stored-energy adjustments is 0.8 kr in Darkstar's favour

#### Scenario: Required end state of charge is unknown
- **WHEN** a slot lacks a valid required end state of charge
- **THEN** that slot is excluded and counted in coverage, and the remaining runs yield an estimate
- **AND** battery_comparison.status is incomplete_period with no amounts only when no usable run remains

#### Scenario: Gap in the middle of the period
- **WHEN** one hour of a 96-slot day was never recorded
- **THEN** battery_comparison.status is estimated with basis configured_losses and coverage 92 covered, 96 total, 4 excluded
- **AND** the hour has no comparison point, and the final points equal the summed totals
- **AND** the actual cash-flow points are unchanged

#### Scenario: Chart lines exclude the stored-energy value
- **WHEN** a stored-energy adjustment is non-zero
- **THEN** legacy cash-flow lines continue to exclude it for compatibility
- **AND** separately named comparison lines include it for either amount-bearing basis

#### Scenario: No battery
- **WHEN** system.has_battery is false
- **THEN** legacy baseline is null with no legacy baseline points
- **AND** battery_comparison.status is no_battery

#### Scenario: Existing fields unchanged
- **WHEN** comparison data is added to a response
- **THEN** actual cash-flow fields and amounts are unchanged

#### Scenario: Current period has a started but unfinished slot
- **WHEN** the current 15-minute slot has not completed
- **THEN** it is excluded from comparison data
- **AND** through identifies the last completed comparison boundary
- **AND** metered started-slot coverage remains unchanged

### Requirement: Comparison diagnostics explain trustworthy history coverage
The cost-series `battery_comparison` SHALL add a separate history diagnostic object with selected cohort identity/start when known, considered/eligible counts and exclusive exclusion counts. It SHALL be returned for provenance-related unavailable states even when no numerical calibration diagnostics exist. Existing calibration/unavailable statuses SHALL remain unchanged; stable reasons SHALL distinguish unverified history, insufficient compatible history and unsupported selected-period measurements from failed numeric validation. No unavailable result SHALL expose comparison amounts. The response SHALL preserve metered costs, legacy fields and existing available comparison economics, and SHALL NOT expose sensor identifiers, evidence paths or raw observations in history diagnostics.

#### Scenario: No trusted legacy history
- **WHEN** every candidate row lacks supported provenance or valid attestation and no usable configured-loss estimate exists
- **THEN** the response has `insufficient_data` with `unverified_history`, zero eligible history and exclusion counts
- **AND** it contains no saving amount or comparison points

#### Scenario: New cohort is collecting samples
- **WHEN** trustworthy compatible rows exist but do not meet the established minimums and no usable configured-loss estimate exists
- **THEN** the response has `insufficient_data` with `insufficient_compatible_history`

#### Scenario: Unsupported selected period
- **WHEN** a valid model exists but every completed selected slot has provenance unsupported by both verified and estimated paths
- **THEN** the response has `incomplete_period` with `unsupported_period_measurements` and coverage of zero covered slots
- **AND** actual costs remain available
- **AND** if only some slots are unsupported, they are excluded and the rest yields a segmented estimate

#### Scenario: Numeric failure remains separate
- **WHEN** trustworthy history is sufficient but existing numeric validation fails and no usable configured-loss estimate exists
- **THEN** status remains `unreliable_model` with its accuracy-failure reason and available diagnostics

### Requirement: API identifies estimate and verified comparison bases
An estimated `battery_comparison` SHALL return its amounts and points with `status: estimated`, `basis: configured_losses`, a clear estimate label, the original calibration status/reason, and bounded counts of assumed legacy recording/SoC-mapping slots. It SHALL omit numerical fit diagnostics unless an actual real fit object exists. A validated fit SHALL use `status: available`, `basis: calibrated`, and real diagnostics. All comparison values and chart points SHALL use the active basis consistently. The response SHALL retain metered cost fields unchanged.

#### Scenario: Estimate with unavailable calibration
- **WHEN** valid period inputs produce a configured-loss estimate while calibration is unavailable
- **THEN** the API identifies the assumptions and the unchanged calibration status/reason

#### Scenario: Estimate after numeric rejection
- **WHEN** real calibration diagnostics exist but fail a numeric gate and estimate inputs are valid
- **THEN** the API labels the amounts as estimated and preserves the actual failed reason and diagnostics

#### Scenario: Automatic verified transition
- **WHEN** strict calibration later passes
- **THEN** the API returns the same economic fields with calibrated basis and actual passing diagnostics
