## ADDED Requirements

### Requirement: Keep-on flag drives charger-on decisions

The executor SHALL treat a slot's per-charger keep-on flag (`ev_keep_on[charger_id] == true`) as an instruction to keep that charger's switch/relay ON even when the slot's planned power for the charger is 0. A single shared predicate (planned kW > 0.1 OR keep-on flag set) SHALL be used at every decision site that derives "this charger should be on" from the slot plan — the switch-close decision, the load balancer's planner-target derivation, and the phase-mode target selection — so the decision rule cannot diverge between sites.

For current-type chargers in keep-on state with 0 planned kW, the load balancer's planner target SHALL be the charger's configured minimum current (the per-charger `min_current_a` config value, not a hardcoded constant), not a power-derived target, so the relay is held closed without misrepresenting demand; the load balancer MAY throttle or shed this target under fuse stress like any other EV demand.

`SlotPlan` SHALL carry the per-charger keep-on flags parsed from the schedule's `ev_keep_on` field; schedules without the field SHALL parse as no-keep-on (empty flags) and behave exactly as before this change.

#### Scenario: Binary charger switch closes on keep-on with zero planned power
- **WHEN** the current slot has `ev_keep_on = {"ev1": true}` and `ev_charger_plans["ev1"] == 0`
- **THEN** the executor SHALL command charger `ev1`'s switch ON

#### Scenario: Current-type charger held at minimum current on keep-on
- **WHEN** a current-type charger with `min_current_a: 8` is in keep-on state with 0 planned kW in the current slot
- **THEN** the load balancer input SHALL carry 8 A (the configured `min_current_a`) as planner target
- **AND** the charger's relay SHALL be commanded closed

#### Scenario: Keep-on charger remains sheddable
- **WHEN** a keep-on charger is held at minimum current and a phase overload occurs
- **THEN** the load balancer MAY throttle or pause that charger following its normal rules

#### Scenario: Schedule without keep-on field is unaffected
- **WHEN** the executor parses a schedule slot with no `ev_keep_on` key
- **THEN** the parsed `SlotPlan` SHALL carry empty keep-on flags
- **AND** all charging decisions SHALL depend solely on planned power, as before

### Requirement: Battery source isolation covers keep-on slots

The executor's EV source-isolation rule (battery discharge blocked while EV charging is scheduled) SHALL also activate when any charger has the keep-on flag set in the current slot, even before any actual EV power draw is measured, so the house battery can never discharge into a keep-on vehicle during the window between switch-close and first measured draw.

#### Scenario: Discharge blocked during keep-on before any measured draw
- **WHEN** the current slot has a keep-on flag set for a charger and measured EV power is 0
- **THEN** the executor SHALL apply the same discharge-blocking source isolation as for a slot with planned EV charging

### Requirement: Keep-on is visible in tick reason text

When the keep-on flag (rather than planned power) is what keeps a charger on, the executor's tick reason/log text SHALL mention keep-on and the affected charger ID(s), so execution history remains auditable without a schema change.

#### Scenario: Reason text names keep-on
- **WHEN** a tick executes a slot where charger `ev1` is on solely due to `ev_keep_on`
- **THEN** the recorded reason text SHALL contain a keep-on indication naming `ev1`

## MODIFIED Requirements

### Requirement: Status API current_slot_plan includes mode_intent

The `get_status()` method SHALL include a `mode_intent` field in the `current_slot_plan` object. This field SHALL be computed by running the Controller's `decide()` method with the current slot plan and current system state. The `current_slot_plan` object SHALL also include `ev_charging_kw` (aggregate across all chargers), `ev_charger_plans` (per-device dict), `ev_keep_on` (per-device keep-on flag dict, empty when no charger is in keep-on state), `discharge_kw`, and `water_heater_plans` from the slot plan.

If the controller cannot produce a decision (e.g., system state unavailable, profile not loaded), `mode_intent` SHALL be `null`.

#### Scenario: Status API returns per-device EV plan
- **WHEN** the executor status is requested and the current slot has per-device EV plans
- **THEN** `current_slot_plan.ev_charger_plans` SHALL contain a dict mapping charger ID to planned kW
- **AND** `current_slot_plan.ev_charging_kw` SHALL be the sum across all chargers

#### Scenario: Status API returns keep-on flags
- **WHEN** the executor status is requested and the current slot has charger `ev1` in keep-on state
- **THEN** `current_slot_plan.ev_keep_on` SHALL contain `{"ev1": true}`

#### Scenario: Status API returns mode_intent for current slot
- **WHEN** the executor status is requested and a current slot exists
- **AND** the controller can evaluate the slot with current system state
- **THEN** `current_slot_plan.mode_intent` contains the controller's mode intent string (one of: `"charge"`, `"self_consumption"`, `"idle"`, `"export"`)

#### Scenario: Status API returns null mode_intent when controller unavailable
- **WHEN** the executor status is requested but system state cannot be gathered (e.g., HA offline)
- **THEN** `current_slot_plan.mode_intent` is `null`
- **AND THEN** all other `current_slot_plan` fields are still populated from the schedule

#### Scenario: Status API includes per-device water heater plans
- **WHEN** the executor status is requested and the current slot has per-device water heater plans
- **THEN** `current_slot_plan.water_heater_plans` SHALL contain the per-device dict (e.g., `{"main_tank": 3.0, "upstairs_tank": 0.0}`)
