# Purpose

TBD - EV charging replanning functionality manages when and how the system triggers schedule recalculations in response to EV plug-in events, ensuring correct async handling, configuration reading, state propagation, and executor switch control.

## Requirements

### Requirement: EV plug-in triggers immediate replan

When an EV plug-in event is received via WebSocket, the system SHALL schedule an immediate replan using the correct async cross-thread dispatch mechanism (`asyncio.run_coroutine_threadsafe`), ensuring the coroutine executes in the main application event loop rather than the WebSocket thread's event loop. The replan trigger SHALL pass the charger ID that triggered the event.

#### Scenario: Replan fires on plug-in with charger context

- **WHEN** the WebSocket receives a plug sensor state change to `on` / `1` / `connected` / `true`
- **THEN** `scheduler_service.trigger_now()` is dispatched with the triggering charger's ID
- **AND** a new schedule is generated with that charger's plug state overridden to `True`

#### Scenario: Silent failure is eliminated

- **WHEN** `_trigger_ev_replan()` is invoked from a background thread
- **THEN** no `RuntimeError` is raised and the error is not silently swallowed

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

### Requirement: Sustained balancer throttling triggers an early replan
The executor SHALL track, per `type: current` EV charger, the continuous duration during which the load balancer holds the charger's setpoint below the planner-derived target (or holds it paused) while the current slot plans charging for it. When this duration exceeds `load_balancing.replan_after_throttled_s` (default 600), the executor SHALL request one planner run through the same replan mechanism used by the plug-in/unplug triggers. Balancer-triggered replans SHALL be rate-limited to at most one per planner interval. The duration tracker SHALL reset whenever the setpoint reaches the planner target, when the slot no longer plans charging for that charger, or when the trigger fires. Reductions that are not caused by the balancer (planner-intended lower targets) SHALL NOT count toward the duration.

#### Scenario: EV held at floor for ten minutes triggers a replan
- **WHEN** the balancer holds a charger at 6 A against a 16 A planner target continuously for `replan_after_throttled_s`
- **THEN** the executor SHALL request one replan
- **AND** the next plan SHALL be computed from the charger's live SoC, reflecting the shortfall

#### Scenario: At most one balancer replan per planner interval
- **WHEN** a balancer-triggered replan fired and throttling persists
- **THEN** no further balancer-triggered replan SHALL fire until a full planner interval has elapsed

#### Scenario: Brief throttling does not replan
- **WHEN** the balancer reduces a charger below target for two minutes and then restores it
- **THEN** no replan SHALL be requested and the duration tracker SHALL reset

#### Scenario: Planner-intended reductions do not count
- **WHEN** the planner target itself is 6 A for a cheap-top-up slot and the balancer is idle
- **THEN** the throttled-duration tracker SHALL NOT accumulate

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
