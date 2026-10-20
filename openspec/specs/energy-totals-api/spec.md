# Energy Totals API

## Purpose

API endpoints for retrieving recorded energy totals, actual metered cost series and matched-coverage DS versus grid-only bill comparisons from the database.

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
The `/api/energy/today` and `/api/energy/range` endpoints SHALL return a non-negative `battery_wear_cost_sek` field representing the modelled battery degradation cost for the requested period, computed from data already aggregated by the endpoint. They SHALL also return `net_cost_incl_wear_sek = net_cost_sek + battery_wear_cost_sek`, and the existing `net_cost_sek` field SHALL be unchanged.

#### Scenario: Wear cost formula
- **WHEN** the endpoint computes `battery_wear_cost_sek`
- **THEN** it equals `(battery_charge_kwh + battery_discharge_kwh) * battery_cycle_cost_kwh * 0.5`
- **AND** `battery_cycle_cost_kwh` is read from `battery_economics.battery_cycle_cost_kwh` in configuration
- **AND** the `* 0.5` factor mirrors the solver's wear model so a full charge+discharge cycle is charged the configured cost per kWh once

#### Scenario: No battery throughput
- **WHEN** there is no battery throughput in the period
- **THEN** `battery_wear_cost_sek` is `0.0`

#### Scenario: Net cost fields
- **WHEN** the endpoint returns cost fields
- **THEN** `net_cost_incl_wear_sek` is the net grid cost with battery wear added
- **AND** `net_cost_sek` remains pure grid import cost minus export revenue

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
`/api/energy/today` and `/api/energy/range` SHALL return `ev_grid_kwh`, `ev_solar_kwh`, `ev_cost_sek` and `ev_solar_share` for the period, computed per slot as defined by the `ev-cost-attribution` capability and summed from `slot_observations`. `ev_cost_sek` SHALL be the EV's grid import cost only and SHALL NOT exceed `import_cost_sek`.

#### Scenario: Existing fields unchanged
- **WHEN** the endpoints return the new EV fields
- **THEN** the existing fields, including `ev_charging_kwh`, `import_cost_sek` and `net_cost_sek`, are unchanged

#### Scenario: Zero-fallback response
- **WHEN** the zero-fallback response is returned
- **THEN** it includes the new fields with 0 values and a null share

#### Scenario: Fields present
- **WHEN** a client calls either endpoint for a period with EV charging
- **THEN** the response SHALL include the four EV cost fields
- **AND** `ev_grid_kwh + ev_solar_kwh` SHALL equal `ev_charging_kwh` within rounding

#### Scenario: Error fallback
- **WHEN** the aggregation fails and the zero fallback is returned
- **THEN** `ev_cost_sek` SHALL be 0 and `ev_solar_share` SHALL be null

### Requirement: Cost series endpoint returns cost per bucket and the running net
`GET /api/energy/cost-series` SHALL accept the same `period` and `start_date`/`end_date` parameters as `/api/energy/range`, resolve them with the same shared period helper, and return cost per bucket from the SlotObservation table, priced the same as `/api/energy/range`. Slots SHALL be bucketed by local hour for a single-day range and by local day otherwise, and the response `bucket` SHALL be `"hour"` or `"day"`.

#### Scenario: Accepted periods and pricing
- **WHEN** the endpoint is called
- **THEN** `period` accepts `today`, `yesterday`, `week`, `month` or `custom`
- **AND** for each slot the import cost is `import_kwh × import_price_sek_kwh` and the export revenue is `export_kwh × export_price_sek_kwh`

#### Scenario: Point contents and ordering
- **WHEN** points are returned
- **THEN** each contains `start` (local ISO time of the bucket), `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` (import minus export) and `cumulative_net_cost_sek` (running sum up to and including the point)
- **AND** points are ordered by time

#### Scenario: Future slots excluded
- **WHEN** the recorder holds rows for slots that have not started yet
- **THEN** those slots are excluded

#### Scenario: Invalid custom range
- **WHEN** the custom range has a bad date format or end before start
- **THEN** the endpoint returns an empty `points` list and an `error` message rather than failing

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

### Requirement: Cost series endpoint returns the grid-only comparison
`GET /api/energy/cost-series` SHALL preserve its period/date/bucket/error contract and top-level actual metered points. It SHALL return a separate `grid_only_comparison` object defined by grid-only-comparison. The new object SHALL NOT fabricate amounts when data is unavailable.

#### Scenario: Preserved actual points and retired fields
- **WHEN** the endpoint responds
- **THEN** the top-level actual metered points, including `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` and `cumulative_net_cost_sek`, keep their existing contract

#### Scenario: Status, reason and coverage
- **WHEN** `grid_only_comparison` is returned
- **THEN** it contains `status`, `reason`, `method_version: grid-only-bill-v1`, and `coverage: {covered_slots, total_slots, excluded_slots}`
- **AND** status/reason is `available/complete_coverage` when all expected completed slots are usable
- **AND** `partial/partial_coverage` when usable slots exist and any completed slot is excluded
- **AND** `no_data/no_completed_observations` when no completed observations exist
- **AND** `unavailable/no_usable_observations` when completed observations exist but none is usable
- **AND** coverage counts the requested period's expected elapsed completed slots, including missing observations, even on no-data/unavailable responses

#### Scenario: Time axis
- **WHEN** a valid period request is answered
- **THEN** `grid_only_comparison` contains `time_axis: {timezone, start, end}` for every status
- **AND** `timezone` is the installation's IANA timezone
- **AND** offset-qualified local ISO `start`/`end` span the full requested period from its first local midnight to the exclusive following midnight, without clipping to completed coverage
- **AND** these bounds support elapsed-UTC chart positioning and installation-local labels even when comparison amounts are unavailable

#### Scenario: Amount-bearing statuses
- **WHEN** the status bears amounts
- **THEN** the object also includes `through`, `grid_only_cost_sek`, zero `grid_only_wear_cost_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `saving_sek`, comparison bucket `points` and covered `segments`
- **AND** each bucket point carries offset-qualified local ISO `start` and exclusive `end`, eligible `import_cost_sek`, `export_revenue_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, zero `grid_only_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `grid_only_cost_sek`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`
- **AND** each segment carries offset-qualified local ISO `start`, exclusive `end`, and boundary `points` with `at`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`, as defined by grid-only-comparison
- **AND** bucket points, segment points and summaries use the same eligible completed slots and reconcile

#### Scenario: Unavailable and invalid responses
- **WHEN** the response is no-data or unavailable
- **THEN** amount fields, comparison points and segments are omitted rather than fabricated as zeros, while `time_axis` is retained
- **AND** invalid period requests retain empty actual points and the existing error response without fabricated comparison amounts

#### Scenario: Excluded content and operations
- **WHEN** `grid_only_comparison` is produced
- **THEN** it does not carry battery inventory, loss factors, reference prices, calibration diagnostics, cohort diagnostics, Estimate/Verified bases or a no-battery status
- **AND** actual range/today totals and separate wear fields remain unchanged
- **AND** no 30-day calibration query, prior-SoC query, self-use replay or fit-cache operation is performed

#### Scenario: New comparison contract
- **WHEN** the request has usable completed inputs
- **THEN** it returns `grid_only_comparison` with bill summaries, coverage and comparison points

#### Scenario: Saving reconciles with summaries and points
- **WHEN** grid-only cost is 40 kr, DS electricity cost is 30 kr and DS wear is 2 kr
- **THEN** `ds_cost_sek` is 32 kr, `saving_sek` is 8 kr and the final cumulative endpoint difference is 8 kr

#### Scenario: Configured battery flow coverage
- **WHEN** a battery is configured and recorded charge or discharge is missing or has ineligible provenance
- **THEN** that slot is excluded from both sides and coverage reflects the exclusion

#### Scenario: No battery requirement
- **WHEN** no battery is configured but valid recorded consumption/grid inputs exist
- **THEN** grid-only comparison amounts are returned

#### Scenario: Partial period
- **WHEN** an otherwise valid completed 96-slot day lacks four slots
- **THEN** status is partial and coverage is 92 covered, 96 total and 4 excluded
- **AND** summary and comparison points price only those 92 slots on both sides

#### Scenario: Empty completed history
- **WHEN** no completed observations exist in the requested period
- **THEN** status is no_data and no saving or comparison points are returned
- **AND** coverage still reports expected completed slots and zero covered slots

#### Scenario: All recorded inputs unusable
- **WHEN** completed observations exist but all fail required bill-input checks
- **THEN** status is unavailable with zero covered slots and no amounts

#### Scenario: Current period has an unfinished slot
- **WHEN** a recorded slot has started but not completed
- **THEN** top-level actual started-slot accounting retains its existing behavior
- **AND** that slot is excluded from both comparison series and through identifies the last included completed boundary

#### Scenario: Actual information is independent
- **WHEN** comparison data is partial or unavailable
- **THEN** top-level actual cash-flow points and range/today actual and wear-inclusive totals remain available with their existing accounting

#### Scenario: Segment contract preserves an internal gap
- **WHEN** a bucket contains eligible slots on both sides of an excluded slot
- **THEN** its bucket point sums only eligible costs and separate covered segments expose the exact gap boundaries and cumulative values

#### Scenario: DST axis metadata without comparison amounts
- **WHEN** a valid single-day request covers a fall-back day but no usable comparison inputs exist
- **THEN** `time_axis` still identifies the installation timezone and full 25-hour elapsed day
- **AND** no comparison amounts, bucket points or segments are fabricated

#### Scenario: Existing fields unchanged
- **WHEN** comparison data is added to a response
- **THEN** actual cash-flow fields and amounts are unchanged
