## ADDED Requirements

### Requirement: EV goal changes trigger an immediate replan
When a charger's goal changes — set, updated or cleared via `POST /api/ev/chargers/{id}/schedule`, changed via an HA `state_changed` event on the charger's goal entities, or adopted from HA during startup/reconnect reconciliation — the backend SHALL request an immediate planner run with reason goal-change. The request SHALL be dispatched without delaying the originating HTTP response or websocket handler, SHALL execute on the main application event loop (cross-thread dispatch from the websocket thread), and SHALL be subject to planner-run coalescing. HA echoes ignored by the write-back debounce and reconciliation that changes nothing SHALL NOT trigger a replan.

#### Scenario: Executor waits for its next tick
- **WHEN** a goal-triggered planner run completes
- **THEN** the backend SHALL NOT trigger an immediate executor run
- **AND** the executor SHALL apply the new plan on its next regular tick

#### Scenario: Goal saved in the dashboard
- **WHEN** the user saves a goal via the API
- **THEN** the endpoint SHALL return without waiting for the planner
- **AND** a planner run SHALL start within the goal-change debounce window

#### Scenario: Goal cleared
- **WHEN** the goal is cleared via the API
- **THEN** a planner run SHALL be triggered so scheduled goal charging is removed from the plan

#### Scenario: Goal changed in HA
- **WHEN** the user changes the HA target-SoC entity mapped to a charger
- **THEN** a planner run SHALL be triggered

#### Scenario: Darkstar's own write echoed back by HA
- **WHEN** an HA `state_changed` echo arrives within the 5-second write-back debounce
- **THEN** no additional replan SHALL be triggered by the echo

#### Scenario: Reconnect with no changes
- **WHEN** the websocket reconnects and the HA goal values equal the state-file goal
- **THEN** no replan SHALL be triggered by reconciliation

### Requirement: All replan triggers share one dispatch helper
Plug-in/unplug replans, goal-change replans and executor-requested replans SHALL be dispatched through one shared helper that selects the correct dispatch mechanism for the calling thread and carries a reason and optional per-charger plug overrides. Divergent per-caller dispatch implementations are a defect.

#### Scenario: Plug-in replan uses the shared helper
- **WHEN** a charger is plugged in
- **THEN** the replan SHALL be dispatched through the shared helper with reason plug-in and the plug override for that charger
