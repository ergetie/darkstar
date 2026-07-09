## MODIFIED Requirements

### Requirement: Write endpoint sets a charger's charging goal
The API SHALL expose `POST /api/ev/chargers/{id}/schedule` accepting a JSON body with `target_soc_percent` (int 0–100, or null to clear), `ready_by` (`HH:MM`), `repeat` (`daily`|`weekdays`|`weekends`|`every_n_days`|`none`), optional `n_days` (int ≥ 1, used with `repeat: every_n_days`), optional `ready_by_date` (ISO date, required when `repeat: none`), and optional `keep_on_after_target` (bool). **No `charge_priority` parameter** — surplus ordering is owned by `excess_pv.priority[]`, not per-charger. The endpoint SHALL validate inputs and persist the goal to `data/ev_multi_day_state.json`. `ready_by_date` SHALL be validated as a real calendar date (`date.fromisoformat`, not regex only) and SHALL NOT be in the past; violations return HTTP 422. `n_days` SHALL round-trip: persisted, preserved by planner writebacks, and returned by GET.

#### Scenario: Set a daily goal
- **WHEN** `POST /api/ev/chargers/ev_charger_1/schedule` is called with `{ "target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily" }`
- **THEN** the endpoint SHALL persist that goal (with `source: "api"`) for `ev_charger_1`
- **AND** SHALL return the updated charger state with HTTP 200

#### Scenario: Set an every-N-days goal
- **WHEN** the body has `repeat: "every_n_days"`, `n_days: 3`, `ready_by: "07:00"`
- **THEN** the goal SHALL be persisted with `n_days: 3`
- **AND** `GET /api/ev/chargers` SHALL return `n_days: 3` even after subsequent planner runs

#### Scenario: Impossible calendar date rejected
- **WHEN** the body has `ready_by_date: "2026-02-31"`
- **THEN** the endpoint SHALL return HTTP 422

#### Scenario: Past date rejected
- **WHEN** the body has `repeat: "none"` and `ready_by_date` is yesterday
- **THEN** the endpoint SHALL return HTTP 422 (a past one-off can never be acted on)

#### Scenario: Clear the goal
- **WHEN** the body has `target_soc_percent: null`
- **THEN** the endpoint SHALL clear the active goal for that charger (the charger reverts to soaking surplus PV only)

#### Scenario: Invalid charger ID
- **WHEN** `{id}` does not match a configured charger
- **THEN** the endpoint SHALL return HTTP 404 "Charger not found"

#### Scenario: Target out of range
- **WHEN** `target_soc_percent: 150`
- **THEN** the endpoint SHALL return HTTP 422 "target_soc_percent must be between 0 and 100"

#### Scenario: Repeat none without a date
- **WHEN** `repeat: "none"` and `ready_by_date` is absent
- **THEN** the endpoint SHALL return HTTP 422 "ready_by_date is required when repeat is none"

### Requirement: State file is source of truth for the user-set goal
`data/ev_multi_day_state.json` SHALL be the **sole** source of truth for charging goals. The pipeline SHALL read goals only from the state file; `config.yaml` goal fields are removed and SHALL NOT be used as a fallback. Planner writebacks SHALL preserve all user-set goal fields verbatim (including `n_days`) and SHALL preserve entries for chargers not processed in the current run (e.g. temporarily disabled chargers).

#### Scenario: No goal in state file means no goal
- **WHEN** the state file has no goal for a charger
- **THEN** the pipeline SHALL treat the charger as having no charging goal (no config fallback)

#### Scenario: Planner writeback preserves goals
- **WHEN** the planner persists progress for charger A while charger B is disabled in config
- **THEN** charger B's goal entry SHALL remain in the state file unchanged

#### Scenario: State file missing or corrupt
- **WHEN** the state file does not exist or cannot be parsed
- **THEN** the pipeline SHALL treat all chargers as having no goal and log a warning
- **AND** the API SHALL recreate the state file on next write

## ADDED Requirements

### Requirement: State-file access is serialized across writers
All reads and writes of `data/ev_multi_day_state.json` SHALL go through `backend/core/ev_state.py`, which SHALL hold an inter-process/inter-thread file lock across each read-modify-write cycle and SHALL write via a uniquely named temp file followed by an atomic rename. Concurrent writers (API endpoint, HA websocket handler, planner persist) SHALL NOT lose each other's updates or corrupt the file.

#### Scenario: API write during planner persist
- **WHEN** a goal is saved via the API while the planner is persisting progress
- **THEN** both updates SHALL be present in the final file (no lost update, no partial JSON)

#### Scenario: Unique temp files
- **WHEN** two writers write concurrently
- **THEN** each SHALL use its own temp file (no shared `.tmp` path)

### Requirement: Backend owns its HA client sessions per event loop
HTTP calls to Home Assistant from the backend (API routers, HA websocket sync) SHALL use an HA client whose aiohttp session is bound to the calling event loop, created and closed by the backend. The backend SHALL NOT borrow the executor's HA client, and no code path SHALL close or rebind a session owned by another event loop.

#### Scenario: Schedule save does not disturb the executor
- **WHEN** a schedule is saved (triggering HA sync) while the executor is sending a hardware command
- **THEN** the executor's HTTP session SHALL remain open and its command SHALL complete normally

#### Scenario: Sessions cleaned up on shutdown
- **WHEN** the backend shuts down
- **THEN** backend-owned HA client sessions SHALL be closed (no leaked sessions per save)
