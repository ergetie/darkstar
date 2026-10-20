## RENAMED Requirements

- FROM: `### Requirement: Cost series endpoint returns the without-Darkstar baseline`
- TO: `### Requirement: Cost series endpoint returns the grid-only comparison`

## MODIFIED Requirements

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
