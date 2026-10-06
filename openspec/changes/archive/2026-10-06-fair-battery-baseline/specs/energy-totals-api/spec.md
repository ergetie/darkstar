## MODIFIED Requirements

### Requirement: Cost series endpoint returns the without-Darkstar baseline
`GET /api/energy/cost-series` SHALL preserve its existing actual metered `import_cost_sek`, `export_revenue_sek`, `net_cost_sek` and `cumulative_net_cost_sek` fields and legacy `baseline` fields for compatibility. It SHALL add a separately named `battery_comparison` object for the validated estimate defined by `no-darkstar-baseline` and `battery-comparison-calibration`. Legacy baseline data SHALL NOT be represented as a validated estimate or used as a fallback for the new comparison.

`battery_comparison` SHALL carry `status`, stable `reason` code, `method_version`, `through`, and available calibration diagnostics, including factors, training/validation windows, sample counts and validation errors. Status SHALL be one of `available`, `insufficient_data`, `unreliable_model`, `incomplete_period`, `no_battery`, or `no_data`. When available it SHALL contain `darkstar` and `self_use` summaries, each with `grid_cost_sek`, `wear_cost_sek`, `stored_energy_change_kwh`, `stored_energy_value_sek` and `comparison_cost_sek`, plus `saving_sek`, `reference_price_sek_kwh`, and bucketed comparison `points`. Each point SHALL contain bucket `start`, `darkstar_cumulative_comparison_cost_sek` and `self_use_cumulative_comparison_cost_sek`. When unavailable, summaries, savings and comparison points SHALL be absent rather than zero-filled.

Comparison points SHALL cumulatively include modeled grid cost, wear and stored-energy valuation using the same period reference price at every boundary. Final endpoints SHALL equal their corresponding summary comparison costs, and saving SHALL equal their difference, within rounding. Original cash-flow points SHALL retain original accounting and started-slot coverage; comparison points SHALL include only completed observations and valid measured end SoC at each bucket boundary. Single-day estimates SHALL bucket by local hour and longer estimates by local day, retaining distinct UTC identities across DST.

#### Scenario: Baseline fields present with a battery
- **WHEN** a battery installation has recorded slots
- **THEN** existing legacy baseline fields retain compatibility
- **AND** the response independently reports availability of `battery_comparison`

#### Scenario: Last baseline cumulative matches the baseline total
- **WHEN** legacy baseline points are returned
- **THEN** the final legacy cumulative continues to equal legacy `baseline.net_cost_sek`
- **AND** each validated comparison endpoint equals its respective comparison summary

#### Scenario: Saving matches the definition
- **WHEN** validated self-use and Darkstar comparison totals are 40 kr and 30 kr
- **THEN** `battery_comparison.saving_sek` is 10 kr
- **AND** the difference between final comparison endpoints is 10 kr

#### Scenario: Stored-energy fields
- **WHEN** Darkstar retains 0.4 kWh more and the common reference price is 2.0 kr/kWh
- **THEN** the difference between stored-energy adjustments is 0.8 kr in Darkstar's favour

#### Scenario: Real end state of charge unknown
- **WHEN** the final completed slot lacks valid real SoC
- **THEN** `battery_comparison.status` is `incomplete_period`
- **AND** no comparison amounts are exposed

#### Scenario: Chart lines exclude the stored-energy value
- **WHEN** a stored-energy adjustment is non-zero
- **THEN** legacy cash-flow lines continue to exclude it for compatibility
- **AND** separately named validated comparison lines include it

#### Scenario: No battery
- **WHEN** `system.has_battery` is false
- **THEN** legacy `baseline` is null with no legacy baseline points
- **AND** `battery_comparison.status` is `no_battery`

#### Scenario: Existing fields unchanged
- **WHEN** validated comparison data is added to a response
- **THEN** actual cash-flow fields and amounts are unchanged

#### Scenario: Current period has a started but unfinished slot
- **WHEN** the current 15-minute slot has not completed
- **THEN** it is excluded from comparison data
- **AND** `through` identifies the last completed comparison boundary
- **AND** metered started-slot coverage remains unchanged
