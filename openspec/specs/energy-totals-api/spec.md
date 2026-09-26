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
