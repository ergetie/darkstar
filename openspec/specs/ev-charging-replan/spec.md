# Purpose

Defines when and how the system triggers schedule replans for EV events such as plug-in, unplug, sustained load-balancer throttling and goal changes, including async dispatch and plug-state interpretation.

## Requirements
### Requirement: EV plug-in triggers immediate replan
When an EV plug-in event is received via WebSocket, the system SHALL derive the connected boolean using that charger's configured `plugged_in_states` and schedule an immediate replan only when the derived state transitions from disconnected to connected, passing the charger ID that triggered the event.

#### Scenario: Cross-thread dispatch
- **WHEN** the replan is scheduled from the WebSocket thread
- **THEN** it uses `asyncio.run_coroutine_threadsafe`
- **AND** the coroutine executes in the main application event loop rather than the WebSocket thread's event loop

#### Scenario: Replan fires on configured plug-in state
- **WHEN** the WebSocket receives a plug sensor change from a disconnected state to any state listed in that charger's `plugged_in_states`
- **THEN** `scheduler_service.trigger_now()` is dispatched with the triggering charger's ID
- **AND** a new schedule is generated with that charger's plug state overridden to `True`

#### Scenario: Connected-to-connected transition does not replan
- **WHEN** a charger config lists both `WaitCar` and `Charging` as connected states
- **AND** its sensor changes from `WaitCar` to `Charging`
- **THEN** the live charger state SHALL remain connected
- **AND** no additional plug-in replan SHALL be triggered

#### Scenario: Silent failure is eliminated

- **WHEN** `_trigger_ev_replan()` is invoked from a background thread
- **THEN** no `RuntimeError` is raised and the error is not silently swallowed

### Requirement: Plug state mappings are normalized and shared
The system SHALL split `plugged_in_states` on commas, trim surrounding whitespace, discard empty entries, and compare raw HA states case-insensitively, using `on,true,1,connected` if the field is absent. A raw state not in the configured set SHALL be treated as disconnected. Exactly one shared interpretation SHALL be used by every consumer of `plug_sensor`.

#### Scenario: Consumers of the shared interpretation
- **WHEN** a consumer derives a connected boolean from `plug_sensor`
- **THEN** it uses the shared interpretation, specifically the planner/initial per-device HA read, the WebSocket live and aggregate state, the EV dashboard API, the system-status aggregate, and plug/unplug replan decisions
- **AND** no consumer derives the connected boolean from a generic boolean helper or a hardcoded state set

#### Scenario: Multi-charger aggregation
- **WHEN** connected states are aggregated across multiple chargers
- **THEN** each charger's raw state is resolved against that charger's own `plugged_in_states` before aggregation

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

### Requirement: EV replan config path reads from `ev_chargers[]`

The `_trigger_ev_replan()` function SHALL read the `replan_on_plugin` and `replan_on_unplug` settings from the specific charger whose plug sensor fired the event, not from the first enabled charger or a global setting.

#### Scenario: Charger A has replan disabled, charger B has replan enabled

- **WHEN** charger A has `replan_on_plugin: false` and charger B has `replan_on_plugin: true`
- **AND** charger A's plug sensor fires a plug-in event
- **THEN** `_trigger_ev_replan()` SHALL NOT trigger a replan

#### Scenario: Charger B plug-in triggers replan

- **WHEN** charger B has `replan_on_plugin: true`
- **AND** charger B's plug sensor fires a plug-in event
- **THEN** `_trigger_ev_replan()` SHALL trigger a replan

#### Scenario: Charger with default replan settings

- **WHEN** a charger has no explicit `replan_on_plugin` setting (defaults to true)
- **AND** its plug sensor fires a plug-in event
- **THEN** a replan SHALL be triggered

### Requirement: Planner receives live WebSocket plug state on replan-on-plugin

When a replan is triggered by a plug-in WebSocket event, the system SHALL pass the known plug state (`ev_plugged_in=True`) directly into `get_initial_state()` as an override for the specific charger that triggered the event, bypassing the HA REST API re-fetch for that charger only.

#### Scenario: REST lag does not cause empty EV plan

- **WHEN** the planner is triggered within 3 seconds of charger A's plug-in event
- **THEN** the generated schedule includes charging slots for charger A (assuming price and SoC conditions are met)
- **AND** charger B's plug state is fetched from HA REST API as normal

#### Scenario: Override applies only for plug-in trigger

- **WHEN** the planner is triggered by the normal scheduled cycle (not a plug-in event)
- **THEN** `get_initial_state()` fetches plug state for all chargers from HA REST API as usual

### Requirement: Per-device plug sensor to charger ID mapping
The WebSocket client SHALL maintain a mapping from plug sensor entity IDs to charger IDs. When a plug sensor fires, the system SHALL look up the corresponding charger ID and use that charger's `replan_on_plugin`/`replan_on_unplug` setting.

#### Scenario: Plug sensor mapped to correct charger

- **WHEN** charger "tesla" has `plug_sensor: "binary_sensor.tesla_plug"` and charger "leaf" has `plug_sensor: "binary_sensor.leaf_plug"`
- **AND** `binary_sensor.tesla_plug` fires a state change
- **THEN** the system SHALL identify this as charger "tesla" and check tesla's replan settings

#### Scenario: Unknown plug sensor ignored

- **WHEN** a state change arrives for a sensor not mapped to any charger
- **THEN** the system SHALL ignore the event (no replan triggered)

### Requirement: Per-device unplug replan
The WebSocket client SHALL trigger a replan on unplug events for chargers that have `replan_on_unplug: true`. The charger ID SHALL be passed to the replan trigger.

#### Scenario: Charger with replan_on_unplug enabled

- **WHEN** charger A has `replan_on_unplug: true`
- **AND** charger A's plug sensor fires an unplug event
- **THEN** a replan SHALL be triggered
- **AND** the new schedule SHALL reflect charger A as unplugged

#### Scenario: Charger with replan_on_unplug disabled (default)

- **WHEN** charger B has `replan_on_unplug: false` (or default)
- **AND** charger B's plug sensor fires an unplug event
- **THEN** no replan SHALL be triggered

### Requirement: EV charger switch is controlled exclusively by schedule

The executor SHALL only enable the EV charger switch when `scheduled_ev_charging` is `True`. Actual detected power draw (`actual_ev_charging`) SHALL NOT be used as a gate to allow charging — it is used only for source isolation (blocking battery discharge).

#### Scenario: No plan, car draws power

- **WHEN** no EV charging slot exists in the current schedule AND the EV is physically drawing power
- **THEN** the executor does NOT assert `ev_should_charge = True` for switch control purposes

#### Scenario: Plan exists, car is not drawing power yet

- **WHEN** a schedule slot with `ev_charging_kw > 0.1` exists for the current interval
- **THEN** the executor asserts `ev_should_charge = True` and opens the EV switch

#### Scenario: Source isolation still active when unscheduled charging detected

- **WHEN** `actual_ev_charging` is `True` and `scheduled_ev_charging` is `False`
- **THEN** battery discharge is still blocked (source isolation) even though the switch is not actively commanded ON

### Requirement: WebSocket EV monitoring respects config reload

The WebSocket EV monitoring SHALL fully tear down EV charger state when `system.has_ev_charger` is set to false and config is reloaded. This ensures the system-level toggle acts as a proper master gate for all EV monitoring.

#### Scenario: Disabling has_ev_charger clears EV monitoring

- **WHEN** `system.has_ev_charger` is changed from `true` to `false` and config is reloaded
- **THEN** the WebSocket client SHALL clear `ev_charger_configs` to an empty list
- **AND** remove `ev_chargers` from `latest_values`
- **AND** stop monitoring all EV charger sensor entities

#### Scenario: Re-enabling has_ev_charger restores EV monitoring

- **WHEN** `system.has_ev_charger` is changed from `false` to `true` and config is reloaded
- **THEN** the WebSocket client SHALL rebuild EV charger monitoring from the `ev_chargers[]` config array
- **AND** only monitor chargers with `enabled: true`

#### Scenario: Disabling all individual chargers clears EV state

- **WHEN** `system.has_ev_charger` is `true` but all chargers in `ev_chargers[]` have `enabled: false`
- **THEN** the WebSocket client SHALL have an empty `ev_charger_configs` list
- **AND** `latest_values["ev_chargers"]` SHALL be an empty list

### Requirement: EV goal changes trigger an immediate replan
When a charger's goal changes, the backend SHALL request an immediate planner run with reason goal-change, dispatched without delaying the originating HTTP response or websocket handler, executed on the main application event loop, and subject to planner-run coalescing. HA echoes ignored by the write-back debounce and reconciliation that changes nothing SHALL NOT trigger a replan.

#### Scenario: Goal change sources
- **WHEN** a goal is set, updated or cleared via `POST /api/ev/chargers/{id}/schedule`
- **OR** changed via an HA `state_changed` event on the charger's goal entities
- **OR** adopted from HA during startup/reconnect reconciliation
- **THEN** the backend requests an immediate planner run with reason goal-change

#### Scenario: Cross-thread dispatch
- **WHEN** the change originates on the websocket thread
- **THEN** the request is dispatched cross-thread onto the main application event loop

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
