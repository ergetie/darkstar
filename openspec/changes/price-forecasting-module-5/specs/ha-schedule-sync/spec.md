## ADDED Requirements

### Requirement: Backend subscribes to the HA ready-by and target-SoC entities
When a charger has `ha_ready_by_entity` (`input_datetime`) and/or `ha_target_soc_entity` (`input_number`) configured, the backend SHALL subscribe to `state_changed` events for those entities via the existing HA WebSocket connection and update the charger's goal in `data/ev_multi_day_state.json` when they change.

#### Scenario: User sets the ready-by time in HA
- **WHEN** the user sets `input_datetime.ev_ready_by` to `"2026-06-12 07:00:00"` and the charger maps `ha_ready_by_entity` to it
- **THEN** the backend SHALL parse the datetime and update that charger's ready-by in the state file

#### Scenario: User sets the target SoC in HA
- **WHEN** the user sets `input_number.ev_target_soc` to `90` and the charger maps `ha_target_soc_entity` to it
- **THEN** the backend SHALL update that charger's `target_soc_percent` to 90 in the state file

#### Scenario: HA value takes priority
- **WHEN** an HA-mapped value is set
- **THEN** the HA value SHALL take precedence over the dashboard-set value for that field (mirroring the vacation-mode override)

### Requirement: Backend reads the HA entities on startup
On startup, for each charger with HA entities configured, the backend SHALL read their current values. If the state file has no goal for that charger and HA has valid values, the HA values SHALL seed the goal; if the state file already has a goal, the backend SHALL write it back to the HA entities to resync.

#### Scenario: HA has values, state file empty
- **WHEN** the backend starts, the HA entities have valid values, and the state file has no goal for the charger
- **THEN** the backend SHALL seed the state-file goal from the HA values

#### Scenario: State file already has a goal
- **WHEN** both HA and the state file have values on startup
- **THEN** the state file goal SHALL take precedence and SHALL be written back to the HA entities

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

### Requirement: input_datetime added to allowed service domains
The `HAClient.call_service()` domain allowlist SHALL include `input_datetime` (service `set_datetime`) for write operations. Target-SoC writes SHALL reuse the already-allowed `input_number.set_value`.

#### Scenario: call_service with input_datetime
- **WHEN** `call_service(domain="input_datetime", service="set_datetime", …)` is called
- **THEN** the domain guard SHALL allow it and the service SHALL execute
