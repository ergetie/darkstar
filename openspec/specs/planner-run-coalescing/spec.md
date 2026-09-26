# planner-run-coalescing Specification

## Purpose
Ensure planner run requests that arrive while a run is in progress are coalesced into a single follow-up run instead of being dropped, so goal changes and plug events are never lost.
## Requirements
### Requirement: Planner run requests are coalesced, never dropped
When a planner run is requested while another run is in progress, the planner service SHALL record that a follow-up run is required and SHALL execute exactly one additional run after the in-progress run finishes (whether it succeeded or failed). Multiple requests arriving during one in-progress run SHALL collapse into that single follow-up run. EV plug-state overrides carried by queued requests SHALL be merged per charger, with the most recent value for a charger winning, and applied to the follow-up run. A request SHALL NOT be answered with a "Planner already running" failure.

#### Scenario: Request during a running plan
- **WHEN** a goal-change replan is requested while a scheduled run is solving
- **THEN** the request SHALL be acknowledged as queued
- **AND** exactly one further run SHALL start after the current run completes

#### Scenario: Several requests during one run
- **WHEN** three replan requests arrive while one run is in progress
- **THEN** exactly one follow-up run SHALL execute after it

#### Scenario: Follow-up after a failed run
- **WHEN** the in-progress run fails and a follow-up was requested
- **THEN** the follow-up run SHALL still execute

#### Scenario: Plug override survives coalescing
- **WHEN** a plug-in replan for `ev_charger_1` (override plugged=True) arrives while a run is in progress
- **THEN** the follow-up run SHALL apply plugged=True for `ev_charger_1`

### Requirement: Goal-change replan requests are debounced
Replan requests with reason goal-change SHALL be debounced for a short fixed window (about 2 seconds) so that a burst of goal edits (for example HA updating target SoC and ready-by as two separate events) results in one planner run. Plug-event replan requests SHALL NOT be debounced.

#### Scenario: HA edits two goal fields in quick succession
- **WHEN** HA changes the target SoC and, one second later, the ready-by for the same charger
- **THEN** exactly one planner run SHALL be triggered for that burst

#### Scenario: Plug event is not delayed
- **WHEN** a charger is plugged in
- **THEN** the plug-in replan SHALL be dispatched without the goal-change debounce

### Requirement: Manual planner run waits for the coalesced run
A synchronous manual planner run (`POST /api/run_planner`) requested while a run is in progress SHALL wait for and return the result of the coalesced follow-up run instead of returning an error.

#### Scenario: User clicks Run Planner during a goal replan
- **WHEN** the user clicks Run Planner while a goal-triggered run is in progress
- **THEN** the request SHALL complete when the follow-up run completes and return its result
