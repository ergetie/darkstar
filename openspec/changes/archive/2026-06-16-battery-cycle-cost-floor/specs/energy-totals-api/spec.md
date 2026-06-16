## ADDED Requirements

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
