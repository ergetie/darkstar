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
When `system.has_battery` is true and the period has started slots, `GET /api/energy/cost-series` SHALL include in each point `baseline_cumulative_net_cost_sek` (the running grid net cost of the baseline defined by the `no-darkstar-baseline` capability, on the same basis and over the same points as `cumulative_net_cost_sek`) and SHALL include a top-level `baseline` object with `net_cost_sek`, `battery_wear_cost_sek`, `net_cost_incl_wear_sek`, `saving_incl_wear_sek`, `stored_energy_difference_kwh` and `stored_energy_value_sek`. The real net plus real battery wear in the saving SHALL use the same wear formula as `/api/energy/range`. `saving_incl_wear_sek` SHALL equal `net_cost_incl_wear_sek` minus the real net cost including wear plus `stored_energy_value_sek` (counted as 0 when null). The two stored-energy fields are defined by the `no-darkstar-baseline` capability, SHALL be rounded like the other baseline amounts and SHALL be `null` when the real end state of charge is unknown. The per-point baseline cumulatives SHALL stay pure grid cash flow and SHALL NOT include the stored-energy value. When `system.has_battery` is false or there are no points, `baseline` SHALL be `null` and points SHALL omit the baseline field. All existing fields and their values SHALL be unchanged.

#### Scenario: Baseline fields present with a battery
- **WHEN** a client calls GET /api/energy/cost-series?period=today with `system.has_battery` true and recorded slots
- **THEN** every point has `baseline_cumulative_net_cost_sek` and `baseline` has the six fields

#### Scenario: Last baseline cumulative matches the baseline total
- **WHEN** the response has points
- **THEN** the last point's `baseline_cumulative_net_cost_sek` equals `baseline.net_cost_sek`

#### Scenario: Saving matches the definition
- **WHEN** the response has a baseline
- **THEN** `saving_incl_wear_sek` equals `baseline.net_cost_incl_wear_sek` minus the period's real net cost including wear plus `baseline.stored_energy_value_sek`

#### Scenario: Stored-energy fields
- **WHEN** the real battery ends the period with 0.4 kWh more stored energy than the simulated one at an average import price of 2.0 and discharge efficiency 1.0
- **THEN** `stored_energy_difference_kwh` is 0.4 and `stored_energy_value_sek` is 0.8

#### Scenario: Real end state of charge unknown
- **WHEN** no started slot has a `soc_end_percent`
- **THEN** both stored-energy fields are `null` and the saving does not include them

#### Scenario: Chart lines exclude the stored-energy value
- **WHEN** the stored-energy value is non-zero
- **THEN** the last `baseline_cumulative_net_cost_sek` still equals `baseline.net_cost_sek`

#### Scenario: No battery
- **WHEN** `system.has_battery` is false
- **THEN** `baseline` is `null` and points have no baseline field

#### Scenario: Existing fields unchanged
- **WHEN** the baseline is present
- **THEN** `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` and `cumulative_net_cost_sek` are identical to the response without the baseline
