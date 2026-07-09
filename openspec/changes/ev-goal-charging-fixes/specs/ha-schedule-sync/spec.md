## MODIFIED Requirements

### Requirement: Backend subscribes to the HA ready-by and target-SoC entities
When a charger has `ha_ready_by_entity` (`input_datetime`) and/or `ha_target_soc_entity` (`input_number`) configured, the backend SHALL subscribe to `state_changed` events for those entities via the existing HA WebSocket connection and update the charger's goal in `data/ev_multi_day_state.json` when they change. The entities SHALL be registered in the websocket's monitored-entities map under `ev_ready_by_{idx}` / `ev_target_soc_{idx}` keys (mirroring the vacation-mode pattern) — subscription without registration is a defect, since the `state_changed` dispatch only fires for registered entities.

#### Scenario: User sets the ready-by time in HA
- **WHEN** the user sets `input_datetime.ev_ready_by` to `"2026-06-12 07:00:00"` and the charger maps `ha_ready_by_entity` to it
- **THEN** the backend SHALL parse the datetime and update that charger's ready-by in the state file

#### Scenario: User sets the target SoC in HA
- **WHEN** the user sets `input_number.ev_target_soc` to `90` and the charger maps `ha_target_soc_entity` to it
- **THEN** the backend SHALL update that charger's `target_soc_percent` to 90 in the state file

#### Scenario: Registration is verifiable
- **WHEN** a charger with `ha_ready_by_entity` configured is loaded
- **THEN** `monitored_entities` SHALL contain that entity ID mapped to `ev_ready_by_{idx}`
- **AND** a `state_changed` for it SHALL reach the goal-update handler (covered by an automated test)

#### Scenario: HA value takes priority
- **WHEN** an HA-mapped value is set
- **THEN** the HA value SHALL take precedence over the dashboard-set value for that field (mirroring the vacation-mode override)

### Requirement: Backend reads the HA entities on startup
On startup and on every websocket reconnect, for each charger with HA entities configured, the backend SHALL read the entities' current values and reconcile with the rule **HA wins, subject to sanity checks**: an HA value SHALL be adopted into the state-file goal when it is sane (target SoC within 1–100; datetime parseable and not in the past). When an HA value fails the sanity check, the backend SHALL keep the state-file value for that field and push it to HA once to resync. The backend SHALL NOT unconditionally push the state file to HA on reconnect — doing so reverts edits the user made in HA while Darkstar was down.

#### Scenario: HA has sane values on startup
- **WHEN** the backend starts and the HA entities hold a future datetime and SoC 90
- **THEN** the state-file goal SHALL be updated to match HA (regardless of what the state file held)

#### Scenario: User edited HA while Darkstar was down
- **WHEN** the user changed the HA target SoC from 80 to 90 while the backend was offline and the backend reconnects
- **THEN** the goal SHALL become 90
- **AND** the backend SHALL NOT write 80 back to HA

#### Scenario: HA holds a past datetime
- **WHEN** the HA `input_datetime` holds a datetime in the past on startup
- **THEN** the backend SHALL NOT adopt it as a goal (no expired one-off goal is seeded)
- **AND** the state-file value (if any) SHALL be pushed to HA to resync

#### Scenario: HA entity unreachable on startup
- **WHEN** a configured HA entity cannot be read
- **THEN** the backend SHALL log a warning and continue without sync for that field
