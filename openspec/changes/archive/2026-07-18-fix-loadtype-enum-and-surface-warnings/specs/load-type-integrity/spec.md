## ADDED Requirements

### Requirement: Load-disaggregation subsystem recognizes every frontend-offered load type
The load-disaggregation subsystem (`backend/loads/`) SHALL recognize every `type` value the frontend can produce for EV chargers (`binary`, `current`) and water heaters (`binary`, `modulating`) as its own distinct, correctly-labeled load type, without falling back to `binary` and without logging an "Invalid load type ... defaulting to binary" warning for any of these values.

#### Scenario: Current-type EV charger loads without a fallback warning
- **WHEN** the backend starts with an EV charger entry whose `type` is `"current"`
- **THEN** the load-disaggregation subsystem registers it with a recognized `current` load type
- **AND** no "Invalid load type" warning is logged for that charger

#### Scenario: Modulating-type water heater loads without a fallback warning
- **WHEN** the backend starts with a water heater entry whose `type` is `"modulating"`
- **THEN** the load-disaggregation subsystem registers it with a recognized `modulating` load type
- **AND** no "Invalid load type" warning is logged for that water heater

#### Scenario: Debug endpoint reports the correct type
- **WHEN** `GET /api/loads/debug` is called with a `current`-type EV charger and a `modulating`-type water heater registered
- **THEN** the response reports each device's actual configured type, not `binary`

### Requirement: Load type validation shares a single source of truth with the runtime load-disaggregation subsystem
`POST /api/config/validate` SHALL validate both `ev_chargers[].type` and water heater `type` against the same set of values the load-disaggregation subsystem's `LoadType` definition recognizes, rather than a separately hardcoded or absent list, so config-accepted values and runtime-understood values cannot silently drift apart. This includes adding a water heater `type` validation check where none previously existed.

#### Scenario: A value accepted by config validation is also accepted by the disaggregator
- **WHEN** `POST /api/config/validate` reports no type-related warning for an `ev_chargers[]` or water heater entry's `type` value
- **THEN** the load-disaggregation subsystem also accepts that same value without falling back or warning

#### Scenario: An unsupported EV charger type is caught by the existing banner
- **WHEN** an `ev_chargers[]` entry has a `type` value the runtime load-type definition does not recognize
- **THEN** `POST /api/config/validate` returns a warning for that entry
- **AND** the existing global config-warning banner in the frontend displays it, since it already renders every warning `POST /api/config/validate` returns

#### Scenario: An unsupported water heater type is now caught
- **WHEN** a water heater entry has a `type` value the runtime load-type definition does not recognize
- **THEN** `POST /api/config/validate` returns a warning for that entry, where previously no check existed
- **AND** the warning has `severity: "warning"` (does not block saving)
