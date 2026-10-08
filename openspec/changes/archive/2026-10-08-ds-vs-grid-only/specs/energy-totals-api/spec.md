## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Comparison diagnostics explain trustworthy history coverage
**Reason**: Grid-only bill arithmetic has no calibration history or physical-model cohort.
**Migration**: Use grid_only_comparison coverage and status for the selected period; retain stored provenance and independent history-audit tools.

### Requirement: API identifies estimate and verified comparison bases
**Reason**: The modeled calibrated/configured-loss comparison is retired.
**Migration**: Consume grid_only_comparison bill amounts and input-coverage statuses without Estimate/Verified labels.
