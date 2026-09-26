## MODIFIED Requirements

### Requirement: Planner can be run from the command bar
The CommandBar SHALL include a Run Planner button that triggers the planner and displays inline progress. The button SHALL call `Api.runPlanner()` then `Api.executor.run()`. Progress SHALL be tracked through phases: `starting → fetching_inputs → fetching_prices → applying_learning → running_solver → applying_schedule → complete / failed`. The button SHALL be disabled while planning is in progress. The button SHALL reflect planner runs started by the server (goal changes, plug events, scheduler) through the same progress events, and SHALL handle the `planner_error` event by showing the failed state and surfacing the error message to the user.

#### Scenario: Planner button shows progress while running
- **WHEN** the user clicks the Run Planner button
- **THEN** the button shows a loading spinner and is disabled until the planner phase reaches `complete` or `failed`

#### Scenario: Planner button returns to normal after completion
- **WHEN** the planner phase reaches `complete`
- **THEN** the button returns to its default state and enables

#### Scenario: Server-started run spins the button
- **WHEN** a goal save triggers a planner run on the server
- **THEN** the button SHALL show the spinner and progress until the run completes or fails

#### Scenario: Planner error is surfaced
- **WHEN** a `planner_error` event is received
- **THEN** the button SHALL show the failed state
- **AND** the error message SHALL be shown to the user (for example as an error toast)
