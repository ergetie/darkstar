## MODIFIED Requirements

### Requirement: Cost series endpoint returns the without-Darkstar baseline
GET /api/energy/cost-series SHALL preserve its existing actual metered import_cost_sek, export_revenue_sek, net_cost_sek and cumulative_net_cost_sek fields and legacy baseline fields for compatibility. It SHALL add a separately named battery_comparison object for the comparison defined by no-darkstar-baseline and battery-comparison-calibration. Legacy baseline data SHALL NOT be represented as a validated or configured-loss comparison or used as a fallback for battery_comparison.

battery_comparison SHALL carry status, stable reason code, method_version, through, and any real calibration diagnostics, including factors, training/validation windows, sample counts and validation errors. Status SHALL be one of available, estimated, insufficient_data, unreliable_model, incomplete_period, no_battery, or no_data. An available result SHALL have basis calibrated; an estimated result SHALL have basis configured_losses and preserve the actual calibration status/reason and only diagnostics from a real fit. Both amount-bearing statuses SHALL contain Darkstar and self-use summaries, each with grid_cost_sek, wear_cost_sek, stored_energy_change_kwh, stored_energy_value_sek and comparison_cost_sek, plus saving_sek, reference_price_sek_kwh and bucketed comparison points. Each point SHALL contain bucket start, darkstar_cumulative_comparison_cost_sek and self_use_cumulative_comparison_cost_sek. An estimated result SHALL be explicitly identified as an estimate and SHALL NOT imply calibration passed. For unavailable statuses, summaries, savings and comparison points SHALL be absent rather than zero-filled. Invalid or unsupported selected-period inputs SHALL NOT produce estimate amounts.

Comparison points SHALL cumulatively include modeled grid cost, wear and stored-energy valuation using the same period reference price at every boundary. Final endpoints SHALL equal their corresponding summary comparison costs, and saving SHALL equal their difference, within rounding. Original cash-flow points SHALL retain original accounting and started-slot coverage; comparison points SHALL include only completed observations and valid required state-of-charge endpoints at each bucket boundary, subject to the estimate and calibration eligibility rules. Single-day comparisons SHALL bucket by local hour and longer comparisons by local day, retaining distinct UTC identities across DST.

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
- **WHEN** the selected period lacks a valid required end state of charge for the chosen comparison basis
- **THEN** battery_comparison.status is incomplete_period
- **AND** no comparison amounts are exposed

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

## ADDED Requirements

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
- **WHEN** a valid model exists but a completed selected slot has provenance unsupported by both verified and estimated paths
- **THEN** the response has `incomplete_period` with `unsupported_period_measurements`
- **AND** actual costs remain available

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
