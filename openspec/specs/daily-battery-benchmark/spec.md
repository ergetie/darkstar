# Spec: Daily Battery Benchmark

## Purpose

Compares each day's actual battery cost with a hindsight-optimal battery schedule, computed from recorded data after the day ends.

## Requirements
### Requirement: Only finished, cleanly recorded days are scored
The benchmark SHALL only use local days whose slots all ended before the run and whose slots (and the preceding start-SoC slot) carry per-component power-history recording provenance with live SoC. Other days SHALL be stored as excluded with a reason. Today and future placeholder rows SHALL never be used.

#### Scenario: Today is never scored
- **WHEN** the benchmark runs at 2026-10-11 00:10
- **THEN** the latest day considered is 2026-10-10

#### Scenario: Legacy recording
- **WHEN** any slot of a day lacks `quality_flags.recording.components`
- **THEN** the day is excluded with reason `not_clean_recording`

#### Scenario: Rare snapshot fallback
- **WHEN** a day has 1 or 2 snapshot-fallback slots and is otherwise clean
- **THEN** it is scored and the snapshot count is stored
- **AND** a day with 3 or more is excluded with reason `not_clean_recording`

#### Scenario: DST day
- **WHEN** a local day has 92 or 100 slots
- **THEN** it is scored over all of them

### Requirement: Same model prices actual, hindsight and no-battery
Actual battery flows SHALL be derived from the meter balance. Actual, hindsight and no-battery schedules SHALL be priced with the same per-slot net-grid cost and wear formula. The hindsight plan SHALL end at the same modelled stored energy as the actual flows.

#### Scenario: Missed value
- **WHEN** actual cost is 10 SEK and hindsight cost is 8 SEK
- **THEN** missed is 2 SEK

#### Scenario: Ending stock is matched
- **WHEN** the actual day ends with 12 kWh more stored than it started
- **THEN** the hindsight plan also ends with exactly that stored energy

#### Scenario: Score with no battery value
- **WHEN** the hindsight value over no-battery is below 1 SEK
- **THEN** missed is stored and score is null

### Requirement: Hindsight plan uses live physics without live preferences
The hindsight solve SHALL use Kepler with the configured power, grid, inverter and export-floor limits, and SHALL disable ramping, curtailment, export-threshold, target-SoC and S-index terms, curtailment, load shedding and limit slacks. It SHALL forbid simultaneous charge and discharge and battery discharge during EV charging. Live planning SHALL be unchanged.

#### Scenario: Not proven optimal
- **WHEN** the solver is infeasible or stops at its time limit
- **THEN** the day is stored as failed with the solver status and no score

#### Scenario: Live planner unaffected
- **WHEN** the live planner runs
- **THEN** its model and output are identical to before this change

### Requirement: Capacity mismatch is caught
The benchmark SHALL compare configured capacity with capacity implied by recorded flows and SoC over the day and previous 6 eligible days, and SHALL exclude the day with both values when they differ by more than 15 % given at least 20 pp of SoC movement. It SHALL never change configuration.

#### Scenario: Module disconnected
- **WHEN** configured capacity is 34.2 kWh and implied capacity is 19 kWh
- **THEN** the day is excluded with reason `capacity_mismatch` and both values

### Requirement: Nightly bounded execution with stored results
The benchmark SHALL run at 00:10 local and once after startup, processing not-yet-stored days from the last 14 days one at a time off the event loop. Results SHALL be stored per day in `system_state` with a version; a stored day SHALL not be recomputed unless its version is outdated or it is stored as failed. It SHALL not publish schedules, send HA commands or change observations.

#### Scenario: Restart
- **WHEN** the app restarts and yesterday is already stored with the current version
- **THEN** no solve runs for yesterday

#### Scenario: Failed day is retried
- **WHEN** a day inside the 14-day window is stored as failed, for any reason
- **THEN** every subsequent run recomputes it until it is scored, excluded, or leaves the window

### Requirement: Read-only API and Grid & Financial integration
`GET /api/energy/battery-benchmark` SHALL return stored per-day results and totals (missed, values, score, status counts) for inclusive local dates, default the last 30 finished days, max 366, and SHALL never trigger a solve. The existing Grid & Financial card SHALL show a "DS vs hindsight" row directly under "DS vs grid-only" in the same style (missed kr, score, scored/total days, ⓘ details with excluded days and reasons), and its cost chart SHALL add a cumulative "Hindsight" line below the DS line with the area between them shaded. Existing grid-only values, line and area SHALL be unchanged.

#### Scenario: Period with excluded days
- **WHEN** the selected 30d range has 22 scored and 3 excluded days
- **THEN** the row shows the missed total and score over the 22 days and "22/25 days"
- **AND** ⓘ lists the 3 excluded days with reasons

#### Scenario: Chart gap equals missed value
- **WHEN** the chart is shown for a multi-day range
- **THEN** at each day end the Hindsight line equals the DS line minus the cumulative missed value of scored days so far
- **AND** excluded days add nothing and are visibly marked

#### Scenario: Today view
- **WHEN** the Today range is selected
- **THEN** no hindsight row or line is shown

#### Scenario: Nothing scored yet
- **WHEN** no day in the range is scored
- **THEN** the row shows the reason instead of 0 kr or 0 %
