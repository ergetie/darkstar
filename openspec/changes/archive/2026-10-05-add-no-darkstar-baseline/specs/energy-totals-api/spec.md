## ADDED Requirements

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
