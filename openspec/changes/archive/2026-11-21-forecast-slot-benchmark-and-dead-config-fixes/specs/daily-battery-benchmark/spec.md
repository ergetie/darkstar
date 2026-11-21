## ADDED Requirements

### Requirement: Infeasible strict hindsight solve is retried with recorded limits
When the strict hindsight solve of a day is not optimal, the benchmark SHALL solve once more with each configured grid import, grid export and inverter AC limit raised, per slot, to the larger of the configured limit and what was recorded in that slot, and SHALL score the day with a `limits_relaxed` warning that records which limits were relaxed.

#### Scenario: EV charging above the import limit
- **WHEN** a recorded slot imported more than the configured maximum grid import, for example while the EV charged
- **THEN** the day is scored with a `limits_relaxed` warning naming the grid import limit
- **AND** it is not stored as failed

#### Scenario: PV surplus above the export limit
- **WHEN** a recorded slot exported more than the configured maximum grid export
- **THEN** the day is scored with a `limits_relaxed` warning naming the grid export limit

### Requirement: Relaxation touches only grid-side limits
In slots that recorded export while violating the export-disabled setting or the export-floor SoC requirement, the relaxed solve SHALL NOT apply that constraint; other slots keep it. The battery's charge and discharge power limits, capacity, SoC bounds, efficiencies and ending stock SHALL stay unchanged. Days that the strict solve scores SHALL be unchanged and SHALL NOT carry the warning.

#### Scenario: Battery limits kept
- **WHEN** the relaxed solve runs
- **THEN** the battery's own charge and discharge power limits and ending stock still apply

#### Scenario: Normal day
- **WHEN** the strict solve is optimal
- **THEN** the record has no `limits_relaxed` warning and the same values as before this change

#### Scenario: Full-swing day
- **WHEN** the battery went from near empty to full within the day within configured limits
- **THEN** the strict solve scores it without a warning

### Requirement: Failure after relaxation has a specific reason
When the relaxed solve is also not optimal, the day SHALL be stored as failed with the reason `infeasible_with_recorded_limits`, or `solver_time_limit` when the solver stopped at its time limit, instead of the generic `solver_not_optimal`. The Grid & Financial card SHALL show a human label for each reason.

#### Scenario: Relaxation does not help
- **WHEN** the day stays infeasible with all limits at recorded values
- **THEN** it is stored as failed with reason `infeasible_with_recorded_limits`

### Requirement: Limits-relaxed warning is shown on the card
The benchmark API SHALL return the `limits_relaxed` warning and the relaxed limits on the day record, and the Grid & Financial card SHALL list the warning in its warnings with plain text, in the same style as the other warnings. The scored day SHALL stay included in the totals.

#### Scenario: Day with relaxed limits
- **WHEN** a scored day carries `limits_relaxed`
- **THEN** the card includes the day in its totals
- **AND** the warnings list shows a short text such as "hindsight limits raised to recorded grid import"

### Requirement: Benchmark version bump recomputes the window
`BENCHMARK_VERSION` SHALL be raised to 3 with this change. Stored days of an older version inside the 14-day window SHALL be recomputed on the next run, and days stored as failed SHALL continue to be retried on every run.

#### Scenario: Previously failed day
- **WHEN** a day stored as failed for `solver_not_optimal` is inside the window
- **THEN** the next run recomputes it and scores it if the relaxed solve is optimal

#### Scenario: Older version
- **WHEN** a scored day is stored with version 2
- **THEN** the next run recomputes it under version 3
