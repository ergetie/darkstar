## MODIFIED Requirements

### Requirement: EV plug-in triggers immediate replan
When an EV plug-in event is received via WebSocket, the system SHALL derive the connected boolean using that charger's configured `plugged_in_states` and schedule an immediate replan only when the derived state transitions from disconnected to connected. The replan SHALL use the correct async cross-thread dispatch mechanism (`asyncio.run_coroutine_threadsafe`), ensuring the coroutine executes in the main application event loop rather than the WebSocket thread's event loop. The replan trigger SHALL pass the charger ID that triggered the event.

#### Scenario: Replan fires on configured plug-in state
- **WHEN** the WebSocket receives a plug sensor change from a disconnected state to any state listed in that charger's `plugged_in_states`
- **THEN** `scheduler_service.trigger_now()` SHALL be dispatched with the triggering charger's ID
- **AND** a new schedule SHALL be generated with that charger's plug state overridden to `True`

#### Scenario: Connected-to-connected transition does not replan
- **WHEN** a charger config lists both `WaitCar` and `Charging` as connected states
- **AND** its sensor changes from `WaitCar` to `Charging`
- **THEN** the live charger state SHALL remain connected
- **AND** no additional plug-in replan SHALL be triggered

#### Scenario: Silent failure is eliminated
- **WHEN** `_trigger_ev_replan()` is invoked from a background thread
- **THEN** no `RuntimeError` SHALL be raised and the error SHALL NOT be silently swallowed

## ADDED Requirements

### Requirement: Plug state mappings are normalized and shared
The system SHALL split `plugged_in_states` on commas, trim surrounding whitespace, discard empty entries, and compare raw HA states case-insensitively. If the field is absent, the system SHALL use `on,true,1,connected`. A raw state not in the configured set SHALL be treated as disconnected.

Exactly one shared interpretation SHALL be used by every consumer of `plug_sensor`, specifically the planner/initial per-device HA read, the WebSocket live and aggregate state, the EV dashboard API, the system-status aggregate, and plug/unplug replan decisions. No consumer SHALL derive the connected boolean from a generic boolean helper or a hardcoded state set.

Where connected states are aggregated across multiple chargers, each charger's raw state SHALL be resolved against that charger's own `plugged_in_states` before aggregation.

#### Scenario: Multiple named connected states are recognized
- **WHEN** `plugged_in_states` is `"WaitCar, Charging, Complete"`
- **THEN** raw states `WaitCar`, `charging`, and ` COMPLETE ` SHALL each be interpreted as connected

#### Scenario: Unlisted charger state is disconnected
- **WHEN** `plugged_in_states` is `"WaitCar, Charging, Complete"`
- **AND** the raw state is `Idle`
- **THEN** the charger SHALL be interpreted as disconnected

#### Scenario: All consumers agree on the same raw state
- **WHEN** the same raw plug state is observed for the same charger by the planner read, a WebSocket event, the EV dashboard API, and the system-status aggregate
- **THEN** all four SHALL derive the same connected boolean

#### Scenario: Per-charger vocabularies do not leak in the aggregate
- **WHEN** charger A lists `WaitCar` as connected and charger B does not
- **AND** both sensors report `WaitCar`
- **THEN** the aggregate SHALL count charger A as connected and charger B as disconnected

#### Scenario: Missing mapping uses legacy defaults
- **WHEN** a charger has no `plugged_in_states` field
- **THEN** `on`, `true`, `1`, and `connected` SHALL be interpreted as connected
