# ha-schedule-sync Specification

## Purpose
TBD - created by archiving change price-forecasting-module-5. Update Purpose after archive.
## Requirements
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

### Requirement: Darkstar writes goal changes back to HA
When the goal is set or cleared via `POST /api/ev/chargers/{id}/schedule` and the charger has the HA entities configured, the backend SHALL write the ready-by to the `input_datetime` (`set_datetime`) and the target SoC to the `input_number` (`set_value`).

#### Scenario: Goal set in Darkstar, synced to HA
- **WHEN** a goal is set via the dashboard for a charger with HA entities configured
- **THEN** the backend SHALL update both HA entities to match

### Requirement: Write-back loop prevention via debounce
The backend SHALL ignore `state_changed` events for a charger's HA entities that arrive within 5 seconds of a Darkstar-initiated write to that charger, to prevent feedback loops.

#### Scenario: Darkstar writes, HA echoes back
- **WHEN** Darkstar writes to an HA entity at T=0 and a `state_changed` echo arrives at T=1
- **THEN** the backend SHALL ignore the echo (within the debounce window)

#### Scenario: Genuine HA change after the window
- **WHEN** a `state_changed` arrives more than 5 seconds after the last Darkstar write
- **THEN** the backend SHALL process it as a genuine HA-side change

### Requirement: HA datetime parsing handles multiple formats
The backend SHALL parse `input_datetime` states in `"YYYY-MM-DD HH:MM:SS"` (HA default), ISO 8601, and ISO 8601 with timezone formats, applying the system timezone when none is present. Unparseable values (time-only, `unknown`, `unavailable`, empty) SHALL be logged and ignored.

#### Scenario: HA default format
- **WHEN** the entity state is `"2026-06-12 07:00:00"`
- **THEN** the backend SHALL parse it in the system timezone

#### Scenario: Time-only value
- **WHEN** the entity state is `"07:00:00"` (no date)
- **THEN** the backend SHALL log a warning and SHALL NOT update the state file

### Requirement: input_datetime plumbing across four surfaces (currently absent)
Module 5's HA sync for the ready-by `input_datetime` requires plumbing that does not exist today. **All four SHALL be added:**
1. **`HAClient.call_service()`** domain allowlist SHALL include `input_datetime` (service `set_datetime`) for write operations; executor SHALL expose a new `set_input_datetime(entity_id, datetime)`. Target-SoC writes SHALL reuse the already-allowed `input_number.set_value`.
2. **`executor/profiles.py` `VALID_DOMAINS`** SHALL include `"input_datetime"` (currently `{"select","number","switch","input_number"}`).
3. **`backend/api/routers/ha.py`** entity-list filter SHALL include `"input_datetime."` (currently only `"input_number."`) so the entity picker surfaces `input_datetime` entities in the UI.
4. **`backend/ha_socket.py`** SHALL register `ev_ready_by_{idx}` / `ev_target_soc_{idx}` monitored-entity keys for each charger with `ha_ready_by_entity` / `ha_target_soc_entity` (alongside the existing `ev_plug_{idx}` mapping), with `state_changed` handlers that update the state-file goal.

#### Scenario: call_service with input_datetime
- **WHEN** `call_service(domain="input_datetime", service="set_datetime", …)` is called
- **THEN** the domain guard SHALL allow it and the service SHALL execute

#### Scenario: input_datetime entities appear in the entity picker
- **WHEN** the frontend Settings entity picker queries `/api/ha/entities`
- **THEN** `input_datetime.*` entities SHALL appear in the results (not just `input_number.*`)

#### Scenario: ha_socket monitors the ready-by / target-SoC entities
- **WHEN** a charger has `ha_ready_by_entity` and/or `ha_target_soc_entity` configured
- **THEN** the backend WebSocket SHALL subscribe to `state_changed` for those entities under the `ev_ready_by_{idx}` / `ev_target_soc_{idx}` keys (mirroring the `ev_plug_{idx}` pattern)

#### Scenario: ValidDomains accepts input_datetime on the executor side
- **WHEN** the executor resolves an override or profile key for an `input_datetime.*` entity
- **THEN** `executor/profiles.py:VALID_DOMAINS` SHALL accept it as valid (no "unknown domain" rejection)

#### Scenario: call_service with input_datetime
- **WHEN** `call_service(domain="input_datetime", service="set_datetime", …)` is called
- **THEN** the domain guard SHALL allow it and the service SHALL execute
