# Spec: Daily Battery Benchmark

## Purpose

Compares each day's actual battery cost with a hindsight-optimal battery schedule, computed from recorded data after the day ends.

## Requirements
### Requirement: Only finished, cleanly recorded days are scored
The benchmark SHALL only score local days whose slots all ended before the run. Each slot, and the preceding start-SoC slot, SHALL carry per-component power-history recording provenance with live SoC; a slot without usable provenance or live SoC, or recorded by snapshot fallback, SHALL count as unverified. Today and future placeholder rows SHALL never be used. Other ineligible days SHALL be stored as excluded with a reason.

#### Scenario: Today is never scored
- **WHEN** the benchmark runs at 2026-10-11 00:10
- **THEN** the latest day considered is 2026-10-10

#### Scenario: Legacy recording
- **WHEN** no slot of a day has `quality_flags.recording.components`
- **THEN** the day is excluded with reason `not_clean_recording`

#### Scenario: DST day
- **WHEN** a local day has 92 or 100 slots
- **THEN** it is scored over all of them

### Requirement: Same model prices actual, hindsight and no-battery
Actual battery flows SHALL be derived from the meter balance. Actual, hindsight and no-battery schedules SHALL be priced with the same per-slot net-grid cost and wear formula. The hindsight plan SHALL end at the same modelled stored energy as the actual flows. Each record SHALL store the stored-energy change (terminal minus initial, after clamping).

#### Scenario: Missed value
- **WHEN** actual cost is 10 SEK and hindsight cost is 8 SEK
- **THEN** missed is 2 SEK

#### Scenario: Ending stock is matched
- **WHEN** the actual day ends with 12 kWh more stored than it started
- **THEN** the hindsight plan also ends with exactly that stored energy
- **AND** the record stores a stored-energy change of 12 kWh

#### Scenario: Score with no battery value
- **WHEN** the hindsight value over no-battery is below 1 SEK
- **THEN** missed is stored and score is null

### Requirement: Hindsight plan uses live physics without live preferences
The hindsight solve SHALL use Kepler with the configured power, grid, inverter and export-floor limits, and SHALL disable ramping, curtailment, export-threshold, target-SoC and S-index terms, load shedding and limit slacks. It SHALL forbid simultaneous charge and discharge and battery discharge during EV charging. Live planning SHALL be unchanged.

#### Scenario: Not proven optimal
- **WHEN** the solver is infeasible or stops at its time limit
- **THEN** the day is stored as failed with the solver status and no score

#### Scenario: Live planner unaffected
- **WHEN** the live planner runs
- **THEN** its model and output are identical to before this change

### Requirement: Capacity mismatch is caught
The benchmark SHALL compare configured capacity with capacity implied by recorded flows and SoC aggregated over the whole eligible history window (the day and up to the previous 6 eligible days). When the values differ by more than 20 % given a SoC range (max minus min) of at least 20 pp within the window, it SHALL record a `capacity_mismatch` warning with both values on the day.

#### Scenario: Configured capacity clearly wrong
- **WHEN** configured capacity is 64 kWh but recorded flows and SoC imply about 40 kWh
- **THEN** the day is scored
- **AND** the record carries a `capacity_mismatch` warning with both values

#### Scenario: Insufficient movement
- **WHEN** the SoC range within the window is below 20 pp
- **THEN** no capacity warning is recorded

### Requirement: Nightly bounded execution with stored results
The benchmark SHALL run at 00:10 local and once after startup, processing not-yet-stored days from the last 14 days one at a time off the event loop. It SHALL not publish schedules, send HA commands or change observations.

#### Scenario: Nightly run
- **WHEN** the benchmark runs at 00:10 local or once after startup
- **THEN** it processes not-yet-stored days from the last 14 days one at a time off the event loop
- **AND** it publishes no schedules, sends no HA commands and changes no observations

### Requirement: Read-only API and Grid & Financial integration
`GET /api/energy/battery-benchmark` SHALL return stored per-day results and totals for inclusive local dates and SHALL never trigger a solve. Per-day results SHALL include a list of non-blocking warnings and the stored-energy change, and totals SHALL include warning counts and the stored-energy change summed over scored days.

#### Scenario: API response contents and range
- **WHEN** `GET /api/energy/battery-benchmark` is called
- **THEN** it returns stored per-day results and totals (missed, values, score, status counts, warning counts, stored-energy change) for inclusive local dates
- **AND** the default range is the last 30 finished days with a maximum of 366
- **AND** no solve is triggered

### Requirement: Unverified slots are tolerated up to a limit
A day with at most 4 unverified slots, counting the start-SoC slot, finite prices and a finite start SoC SHALL be scored with an `unverified_slots` warning and the unverified count. A day with more SHALL be stored as excluded with reason `not_clean_recording`. A day with a missing or non-finite price, or whose start-SoC slot has no finite SoC, SHALL be stored as excluded with reason `missing_values`.

#### Scenario: Rare snapshot fallback
- **WHEN** a day has 1 or 2 snapshot-fallback slots and is otherwise clean
- **THEN** it is scored and the snapshot count is stored
- **AND** the record carries an `unverified_slots` warning with that count

#### Scenario: One unverified slot
- **WHEN** a day has 95 clean slots and 1 slot with no recording information
- **THEN** it is scored
- **AND** the record carries an `unverified_slots` warning with count 1

#### Scenario: Too many unverified slots
- **WHEN** a day has 5 unverified slots, counting snapshot, non-live SoC and missing-provenance slots and the start-SoC slot
- **THEN** the day is excluded with reason `not_clean_recording`

#### Scenario: Unverified slot with missing price
- **WHEN** a day has 1 unverified slot and a missing import or export price
- **THEN** the day is excluded with reason `missing_values`

#### Scenario: Missing start SoC
- **WHEN** the previous day's last slot has no SoC
- **THEN** the day is excluded with reason `missing_values`

### Requirement: Recording gap slots count as unverified and carry no flow
A day slot with missing energy values and/or missing SoC but finite prices SHALL count as one unverified slot, within the same limit of 4. Its missing energy SHALL be treated as 0 kWh for actual, hindsight and no-battery cost, and its missing SoC SHALL be skipped in the capacity fit.

#### Scenario: Recording gap slot
- **WHEN** a day has 95 clean slots and 1 slot with no provenance, zero energy values, NULL SoC and present prices
- **THEN** it is scored
- **AND** the record carries an `unverified_slots` warning with count 1

#### Scenario: Missing energy treated as no flow
- **WHEN** a gap slot has missing energy values
- **THEN** actual and hindsight costs equal those of the same day with 0 kWh in that slot

#### Scenario: Gap slot within the limit
- **WHEN** a day has 1 gap slot and 3 other unverified slots
- **THEN** it is scored with an `unverified_slots` count of 4

#### Scenario: Too many gap slots
- **WHEN** a day has 5 gap slots
- **THEN** the day is excluded with reason `not_clean_recording`

### Requirement: Stored energy is clamped to capacity
When the initial or modelled terminal stored energy is outside [0, capacity], both SHALL be clamped to [0, capacity] and the day scored with a `stock_clamped` warning.

#### Scenario: Stock outside capacity
- **WHEN** a full battery's meter balance keeps charging so the modelled terminal stock exceeds capacity
- **THEN** the terminal stock is clamped to capacity and the day is scored
- **AND** the record carries a `stock_clamped` warning

#### Scenario: Clamped day cannot be solved
- **WHEN** the hindsight solve of a clamped day is not optimal
- **THEN** the day is stored as failed with the solver status, without an error

### Requirement: EV charging slots are detected by average power
A slot SHALL count as EV charging only when its recorded EV energy divided by the slot duration exceeds 20 W; below that, EV energy SHALL still count as demand.

#### Scenario: EV sensor idle noise
- **WHEN** a net-discharge day records about 0.3 W of EV power (7.5e-05 kWh per 15-min slot) in most slots
- **THEN** battery discharge is not forbidden in those slots and the day is scored

#### Scenario: Real EV charging
- **WHEN** a slot records EV energy above 20 W average
- **THEN** the hindsight plan does not discharge the battery in that slot

### Requirement: Capacity fit is robust and never blocks scoring
Implied capacity SHALL be estimated by fitting cumulative stored energy against SoC over all slots of the window rather than filtering individual slots, so quantised and jittering SoC does not bias the estimate. A capacity mismatch SHALL NOT exclude the day; the day SHALL be scored as if no mismatch were found. It SHALL never change configuration.

#### Scenario: Module disconnected
- **WHEN** configured capacity is 34.2 kWh and implied capacity is 19 kWh with sufficient SoC movement
- **THEN** the day is scored normally
- **AND** the record carries a `capacity_mismatch` warning with both values

#### Scenario: Large battery with coarse SoC steps
- **WHEN** configured capacity is 64 kWh, SoC is reported in ~1.15 pp steps with occasional counter-direction jitter steps over 7 days, and the battery moves ~0.2 kWh per slot
- **THEN** the day is scored
- **AND** implied capacity is within 20 % of 64 kWh and no warning is recorded

### Requirement: Results are stored per day with a version
Results SHALL be stored per day in `system_state` with a version; a stored day SHALL not be recomputed unless its version is outdated or it is stored as failed. A change to scoring or exclusion rules SHALL bump the version so days inside the 14-day window are recomputed; days older than the window keep their stored result.

#### Scenario: Restart
- **WHEN** the app restarts and yesterday is already stored with the current version
- **THEN** no solve runs for yesterday

#### Scenario: Failed day is retried
- **WHEN** a day inside the 14-day window is stored as failed, for any reason
- **THEN** every subsequent run recomputes it until it is scored, excluded, or leaves the window

#### Scenario: Previously excluded for capacity mismatch
- **WHEN** a day inside the 14-day window is stored with an older version and reason `capacity_mismatch`
- **THEN** the next run recomputes it under the current rules

### Requirement: Grid & Financial card shows the hindsight comparison
The existing Grid & Financial card SHALL show a "DS vs hindsight" row directly under "DS vs grid-only", and its cost chart SHALL add a cumulative "Hindsight" line below the DS line. Existing grid-only values, line and area SHALL be unchanged.

#### Scenario: Card row style and content
- **WHEN** the Grid & Financial card shows the "DS vs hindsight" row
- **THEN** it appears directly under "DS vs grid-only" in the same style
- **AND** it shows missed kr, score, scored/total days and an ⓘ with excluded days and reasons

#### Scenario: Scored day with warning
- **WHEN** a scored day in the range carries a `capacity_mismatch` warning
- **THEN** the row still shows the result including that day
- **AND** a simple warning text with recorded and configured capacity is shown alongside the result, not as a not-scored day or error

#### Scenario: Scored day with unverified slots or clamped stock
- **WHEN** a scored day carries an `unverified_slots` or `stock_clamped` warning
- **THEN** the row still includes that day
- **AND** a simple warning text is shown, such as "3 of 96 slots not verified"

#### Scenario: Battery ended fuller
- **WHEN** the range has scored days, no score, and the battery ended with more stored energy than it started
- **THEN** the row still shows missed kr without a percentage
- **AND** a muted note says the battery ended that many kWh fuller and that the value shows up the next day

#### Scenario: Chart line and shading
- **WHEN** the cost chart is shown
- **THEN** the cumulative "Hindsight" line is drawn below the DS line with the area between them shaded
- **AND** existing grid-only values, line and area are unchanged

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
