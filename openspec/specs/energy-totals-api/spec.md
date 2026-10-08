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
`GET /api/energy/cost-series` SHALL preserve its period/date/bucket/error contract and top-level actual metered points, including `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` and `cumulative_net_cost_sek`, with existing started-slot coverage. It SHALL replace the legacy self-use `baseline`, per-point `baseline_*` fields and `battery_comparison` with a separately named `grid_only_comparison` object defined by grid-only-comparison. Retired fields SHALL be absent, and consumers SHALL NOT fall back to their values.

`grid_only_comparison` SHALL contain `status`, `reason`, `method_version: grid-only-bill-v1`, and `coverage: {covered_slots, total_slots, excluded_slots}`. Status/reason SHALL be `available/complete_coverage` when all expected completed slots are usable; `partial/partial_coverage` when usable slots exist and any completed slot is excluded; `no_data/no_completed_observations` when no completed observations exist; or `unavailable/no_usable_observations` when completed observations exist but none is usable. Coverage SHALL count the requested period's expected elapsed completed slots, including missing observations, even on no-data/unavailable responses.

For valid period requests, `grid_only_comparison` SHALL also contain `time_axis: {timezone, start, end}` for every status. `timezone` SHALL be the installation's IANA timezone; offset-qualified local ISO `start`/`end` SHALL span the full requested period from its first local midnight to the exclusive following midnight, without clipping to completed coverage. These bounds SHALL support elapsed-UTC chart positioning and installation-local labels even when comparison amounts are unavailable.

Amount-bearing statuses SHALL also include `through`, `grid_only_cost_sek`, zero `grid_only_wear_cost_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `saving_sek`, comparison bucket `points` and covered `segments`. Each bucket point SHALL carry offset-qualified local ISO `start` and exclusive `end`, eligible `import_cost_sek`, `export_revenue_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, zero `grid_only_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `grid_only_cost_sek`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`. Each segment SHALL carry offset-qualified local ISO `start`, exclusive `end`, and boundary `points` with `at`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`, as defined by grid-only-comparison. Bucket points, segment points and summaries SHALL use the same eligible completed slots and SHALL reconcile. No-data/unavailable responses SHALL omit amount fields, comparison points and segments rather than fabricating zeros, while retaining `time_axis`. Invalid period requests SHALL retain empty actual points and the existing error response without fabricated comparison amounts.

The new object SHALL NOT carry battery inventory, loss factors, reference prices, calibration diagnostics, cohort diagnostics, Estimate/Verified bases or a no-battery status. Actual range/today totals and separate wear fields SHALL remain unchanged. No 30-day calibration query, prior-SoC query, self-use replay or fit-cache operation SHALL be performed for this comparison.

#### Scenario: New comparison contract
- **WHEN** the request has usable completed inputs
- **THEN** it returns `grid_only_comparison` with bill summaries, coverage and comparison points
- **AND** legacy `baseline`, `baseline_*` and `battery_comparison` fields are absent

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
