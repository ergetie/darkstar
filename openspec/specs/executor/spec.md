## Purpose

The Executor is responsible for executing scheduled energy management decisions by controlling Home Assistant entities (inverters, water heaters, EV chargers). It bridges the planner's decisions with physical device control.

## Requirements

### Requirement: Executor handles Home Assistant service failures gracefully
The executor SHALL NOT crash when Home Assistant service calls fail or time out. Any errors encountered when communicating with Home Assistant MUST be logged and wrapped in `HACallError` so the executor tick can continue safely and the result log remains intact.

#### Scenario: Home Assistant API times out during a service call
- **WHEN** any `call_service` HTTP request takes longer than the configured timeout
- **THEN** the timeout is caught and wrapped as `HACallError`
- **AND THEN** the retry-with-backoff mechanism attempts up to 3 times before giving up
- **AND THEN** if all retries are exhausted, `HACallError` is raised to the caller

#### Scenario: Home Assistant API times out during water heater control
- **WHEN** the `set_water_temp` service call fails after all retries
- **THEN** the water heater action is recorded as a failed `ActionResult` in the tick result log
- **AND THEN** the rest of the executor tick continues normally (profile actions are still executed)
- **AND THEN** no previously collected action results are lost

### Requirement: call_service uses retry-with-backoff
`HAClient.call_service` SHALL use the same `_retry_with_backoff` mechanism as `get_state`, with 3 attempts and a 1-second base delay, treating `TimeoutError` and `aiohttp.ClientError` as retryable.

#### Scenario: call_service retries a transient network error
- **WHEN** `call_service` posts to the Home Assistant API and the session raises a retryable error (`TimeoutError` or `aiohttp.ClientError`)
- **THEN** `_retry_with_backoff` retries the call up to 3 times with a 1-second base delay before giving up
- **AND** if all attempts fail, `HACallError` is raised to the caller

### Requirement: Timeout handling is tested
A unit test SHALL exist verifying that a `TimeoutError` raised by the HTTP session during `call_service` results in an `HACallError` being raised by the client.

#### Scenario: Unit test verifies timeout raises HACallError
- **WHEN** `tests/executor/test_executor_actions.py::test_call_service_timeout_raises_ha_call_error` runs with a mocked session that raises `TimeoutError` from `call_service`
- **THEN** the test asserts `HACallError` is raised
- **AND** the test asserts `exception_type` on the raised error is `"TimeoutError"`

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

### Requirement: Execution records include ev_charging_kw

The execution record logged by the executor SHALL include the aggregate `ev_charging_kw` value from the ORIGINAL slot plan (before any source isolation override) as well as a `ev_charger_plans` dict with per-device planned kW, so that downstream consumers can identify which chargers were scheduled.

#### Scenario: Per-device EV plans in execution record

- **WHEN** the executor processes a slot with charger A at 11 kW and charger B at 7.4 kW
- **THEN** the execution record includes `ev_charging_kw = 18.4` and `ev_charger_plans = {"ev_charger_1": 11.0, "ev_charger_2": 7.4}`

#### Scenario: Non-EV slot logs zero
- **WHEN** the executor processes a slot with no EV charging planned
- **THEN** the execution record includes `ev_charging_kw = 0.0` and `ev_charger_plans = {}`

### Requirement: Execution records log original planned values before EV override

The execution record's planned fields (`planned_charge_kw`, `planned_discharge_kw`, `planned_export_kw`, `planned_water_kw`) SHALL reflect the ORIGINAL slot plan from `schedule.json`, not the modified slot after source isolation or other runtime overrides.

#### Scenario: Source isolation does not affect logged planned discharge

- **WHEN** the schedule has `battery_discharge_kw = 1.4` for a slot
- **AND** EV source isolation overwrites `discharge_kw` to 0.0 for the controller
- **THEN** the execution record includes `planned_discharge_kw = 1.4`

#### Scenario: Non-EV slots are unaffected

- **WHEN** no source isolation is active
- **THEN** the execution record's planned fields match the slot plan exactly (no change in behavior)

### Requirement: Per-device EV charger config loading
The executor config loader SHALL read per-device EV settings from `ev_chargers[]` entries, building a list of `EVChargerDeviceConfig` objects with `id`, `name`, `switch_entity`, `max_power_kw`, `battery_capacity_kwh`, `replan_on_plugin`, and `replan_on_unplug`. Only enabled chargers SHALL be loaded.

#### Scenario: Two enabled chargers loaded
- **WHEN** `ev_chargers` contains charger A (enabled, switch: "switch.tesla") and charger B (enabled, switch: "switch.leaf")
- **THEN** `ExecutorConfig.ev_chargers` SHALL contain two `EVChargerDeviceConfig` entries with the respective switch entities

#### Scenario: Disabled charger excluded
- **WHEN** charger B has `enabled: false`
- **THEN** only charger A SHALL appear in `ExecutorConfig.ev_chargers`

#### Scenario: Charger with empty switch entity
- **WHEN** a charger has `switch_entity: ""`
- **THEN** its `EVChargerDeviceConfig.switch_entity` SHALL be `None`

### Requirement: Executor reads per-device schedule
The executor SHALL parse the `ev_chargers` dict from each schedule slot to build `ev_charger_plans` in `SlotPlan`. If the `ev_chargers` key is missing (old-format schedule), the executor SHALL fall back to using the aggregate `ev_charging_kw` mapped to the first configured charger.

#### Scenario: New format schedule parsed
- **WHEN** a schedule slot contains `ev_chargers: {"ev_charger_1": {"charging_kw": 11.0}}`
- **THEN** `SlotPlan.ev_charger_plans` SHALL be `{"ev_charger_1": 11.0}`

#### Scenario: Old format schedule fallback
- **WHEN** a schedule slot contains only `ev_charging_kw: 11.0` with no `ev_chargers` key
- **THEN** `SlotPlan.ev_charger_plans` SHALL map the full amount to the first configured charger

### Requirement: Execution records carry isolation reason when source isolation is active

When EV source isolation activates during a tick, the executor SHALL populate the `override_reason` field of the execution record with a descriptive string including scheduled and actual EV power. This applies only when no real override (e.g., quick action, force charge) is already active.

#### Scenario: Source isolation populates override_reason

- **WHEN** EV source isolation is active (`ev_should_charge_block = True`)
- **AND** no real override is active (`override.override_needed = False`)
- **THEN** the execution record's `override_reason` contains a string like `"EV source isolation: 10.0kW scheduled, 0.0kW actual"`

#### Scenario: Real override takes precedence over isolation reason

- **WHEN** both a real override and EV source isolation are active
- **THEN** the execution record's `override_reason` reflects the real override, not the isolation

### Requirement: Per-device water heater executor config
The executor SHALL load per-device water heater configs from the `water_heaters[]` array. Each enabled heater with a `target_entity` SHALL have a `WaterHeaterDeviceConfig` containing `id`, `name`, `target_entity`, and `power_kw`. Temperature setpoints SHALL remain global on `WaterHeaterGlobalConfig`.

#### Scenario: Two heaters with target entities
- **WHEN** `water_heaters[]` contains two enabled entries with `target_entity` values
- **THEN** the executor SHALL create two `WaterHeaterDeviceConfig` objects

#### Scenario: Heater without target entity excluded from control
- **WHEN** an enabled heater has empty `target_entity`
- **THEN** the executor SHALL NOT create a device config for it (no control possible)

#### Scenario: Global temp setpoints unchanged
- **WHEN** the executor loads config
- **THEN** `temp_normal`, `temp_off`, `temp_boost`, `temp_max` SHALL still be read from `executor.water_heater`

### Requirement: Per-device SlotPlan for water heaters
`SlotPlan` SHALL include `water_heater_plans: dict[str, float]` mapping heater ID to planned kW. The aggregate `water_kw` SHALL remain as the sum for backward compatibility.

#### Scenario: Slot plan with two heaters
- **WHEN** the schedule has heater A at 3 kW and heater B at 0 kW
- **THEN** `water_heater_plans` SHALL be `{"main_tank": 3.0, "upstairs_tank": 0.0}`
- **AND** `water_kw` SHALL be `3.0`

#### Scenario: Old-format schedule fallback
- **WHEN** a schedule slot has `water_heating_kw: 3.0` but no `water_heaters` dict
- **THEN** the executor SHALL fall back to the aggregate `water_kw: 3.0` and control only the first heater

### Requirement: Per-device water temperature control
The executor SHALL set temperature for each heater independently based on its per-device plan. For each heater in `water_heater_plans`: if planned kW > 0, set to `temp_normal`; if planned kW == 0, set to `temp_off`. Each heater uses its own `target_entity`.

#### Scenario: Two heaters with different plans
- **WHEN** heater A has planned kW 3.0 and heater B has planned kW 0.0
- **THEN** the executor SHALL call `set_water_temp(heater_A.target_entity, temp_normal)`
- **AND** the executor SHALL call `set_water_temp(heater_B.target_entity, temp_off)`

#### Scenario: All heaters idle
- **WHEN** all heaters have planned kW 0.0
- **THEN** the executor SHALL set all heaters to `temp_off`

### Requirement: Per-device water controller decisions
`ControllerDecision` SHALL include `water_temps: dict[str, int]` mapping heater ID to temperature target. The controller SHALL determine each heater's temperature based on its per-device plan from `SlotPlan.water_heater_plans`.

#### Scenario: Controller decides per-device temperatures
- **WHEN** the controller evaluates a slot with heater A planned at 3 kW and heater B at 0 kW
- **THEN** `water_temps` SHALL be `{"main_tank": 60, "upstairs_tank": 40}` (using global temp_normal and temp_off)

#### Scenario: Backward compatible water_temp field
- **WHEN** per-device plans exist
- **THEN** the scalar `water_temp` field SHALL reflect the maximum temperature across all heaters (for logging/status compat)

### Requirement: Executor fetches current Nordpool import price for battery cost tracking
The executor tick SHALL fetch the current Nordpool import price using `await get_nordpool_data()` directly within the async tick context. If the fetch fails or returns no data, the executor SHALL fall back to 0.5 SEK/kWh.

#### Scenario: Nordpool price fetch succeeds
- **WHEN** the executor tick runs battery cost tracking
- **AND** the Nordpool integration returns price data
- **THEN** the executor uses the real spot price for the current time slot
- **AND** the battery cost record reflects the actual import price

#### Scenario: Nordpool price fetch fails
- **WHEN** the executor tick runs battery cost tracking
- **AND** the Nordpool fetch raises an exception or returns empty data
- **THEN** the executor falls back to 0.5 SEK/kWh
- **AND** the tick continues without interruption

#### Scenario: Nordpool price fetch does not block the event loop
- **WHEN** the executor tick fetches Nordpool prices
- **THEN** the fetch is awaited as a coroutine within the existing async event loop
- **AND** no `asyncio.run()` or nested event loop is used

### Requirement: Water heater sensor reads are gated by has_water_heater flag
The executor and recorder SHALL NOT fetch water heater power sensors when `system.has_water_heater` is `false`. The `water_heaters[]` sensor loop SHALL be skipped entirely when the system flag is disabled.

#### Scenario: Water heating disabled skips sensor reads
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `false`
- **THEN** no HTTP requests are made for water heater sensors
- **AND** no 404 warnings are logged for missing water heater entities

#### Scenario: Water heating enabled reads sensors normally
- **WHEN** the recorder or executor gathers power sensor readings
- **AND** `system.has_water_heater` is `true`
- **THEN** enabled water heater sensors from `water_heaters[]` are fetched as before

### Requirement: EV charger sensor reads are gated by has_ev_charger flag
The recorder SHALL NOT fetch EV charger power sensors when `system.has_ev_charger` is `false`.

#### Scenario: EV charging disabled skips sensor reads
- **WHEN** the recorder gathers power sensor readings
- **AND** `system.has_ev_charger` is `false`
- **THEN** no HTTP requests are made for EV charger sensors

#### Scenario: EV charging enabled reads sensors normally
- **WHEN** the recorder gathers power sensor readings
- **AND** `system.has_ev_charger` is `true`
- **THEN** enabled EV charger sensors from `ev_chargers[]` are fetched as before

### Requirement: Executor background loop cleans up async resources on exit

The `_async_run_loop` method SHALL wrap its main loop in a `try/finally` block that cancels all tracked background tasks and closes the `HAClient` session on every exit path (normal stop, early return, exception). The `OverrideEvaluator` SHALL no longer include `LOW_SOC_EXPORT_PREVENTION` in its evaluation. The `OverrideType` enum SHALL NOT include `LOW_SOC_EXPORT_PREVENTION`. The `low_soc_threshold` parameter SHALL be removed from `OverrideEvaluator.__init__`.

#### Scenario: Normal shutdown closes session
- **WHEN** the stop event is set and the while loop exits
- **THEN** all in-flight background tasks are cancelled
- **AND THEN** `ha_client.close()` is called
- **AND THEN** no `Unclosed client session` warning is logged

#### Scenario: Early return during wait closes session
- **WHEN** the stop event is set during the wait-sleep loop and an early `return` is executed
- **THEN** the `finally` block still executes
- **AND THEN** `ha_client.close()` is called

#### Scenario: Uncaught exception does not mask original error
- **WHEN** an uncaught exception escapes the while loop
- **AND THEN** the `finally` block raises while closing the session
- **THEN** the close error is logged as a warning, not raised
- **AND THEN** the original exception propagates to the caller

#### Scenario: Override evaluator does not evaluate low SoC export prevention
- **WHEN** a slot plan has `export_kw > 0` and current SoC is below the old threshold
- **THEN** the override evaluator SHALL return `OverrideResult(override_needed=False)`
- **AND** the planned export SHALL proceed as scheduled (the planner already ensured SoC is adequate)

### Requirement: Background tasks are cancelled before session close

The `finally` block SHALL cancel all tasks in `_background_tasks` and await their completion (with `return_exceptions=True`) before calling `ha_client.close()`.

#### Scenario: In-flight water boost task cancelled on shutdown
- **WHEN** a water boost task is running when the stop event is set
- **THEN** the task is cancelled before the session is closed
- **AND THEN** no `RuntimeError: Session is closed` occurs

#### Scenario: Empty task set is a no-op
- **WHEN** no background tasks are running
- **THEN** the cancellation step is skipped
- **AND THEN** `ha_client.close()` proceeds normally

### Requirement: Default self_consumption fallback allows PV charging

When the controller selects `self_consumption` mode as the default fallback (no charge, export, or discharge planned), the `charge_value` in the resulting `ControllerDecision` SHALL use the user's configured maximum charge current (`max_charge_a` or `max_charge_w` depending on `control_unit`), not 0.

This ensures that even when the planner schedules no explicit charging action, PV power can still charge the battery. The intentional PV surplus export path (where `charge_kw > 0` results in `charge_value = planned`) SHALL NOT be affected.

#### Scenario: Default self_consumption with no planned charge

- **WHEN** the controller evaluates a slot where `charge_kw = 0`, `export_kw = 0`, `discharge_kw = 0`
- **AND** the battery SoC is above the plan target
- **AND** no EV charging is active
- **THEN** the mode intent SHALL be `"self_consumption"`
- **AND** `charge_value` SHALL equal the user's configured `max_charge_a` (or `max_charge_w` for watt-based control)
- **AND** `write_charge_current` SHALL be `True`

#### Scenario: Planned PV surplus still uses planned charge value

- **WHEN** the controller evaluates a slot where `charge_kw > 0` and `export_kw > 0` and `discharge_kw = 0`
- **THEN** the mode intent SHALL be `"self_consumption"`
- **AND** `charge_value` SHALL be the computed planned charge value from `_calculate_charge_limit`
- **AND** `charge_value` SHALL NOT be overridden to the user's max

#### Scenario: Default self_consumption with watt-based control unit

- **WHEN** the controller evaluates a slot with the default self_consumption fallback
- **AND** the profile's `control_unit` is `"W"`
- **THEN** `charge_value` SHALL equal the user's configured `max_charge_w`

### Requirement: Manual override does not write inverter settings

When the configured `manual_override_entity` is active (`state.manual_override_active` is true), the executor SHALL NOT write any inverter, EV-charger, or water-heater settings for that tick. This mirrors the pause short-circuit and honors the manual-override contract ("executor will not change settings"). State recording (execution history, slot observations) MAY still run so the UI reflects actual conditions.

#### Scenario: Manual override active skips inverter writes

- **WHEN** `state.manual_override_active` is true during a tick
- **THEN** the executor SHALL NOT push any battery mode, `soc_target`, charge/discharge, or export setting to the inverter
- **AND** the executor SHALL NOT write the EV charger switch or water heater setpoint

#### Scenario: Manual override inactive behaves normally

- **WHEN** `state.manual_override_active` is false
- **THEN** the executor SHALL evaluate and apply the plan as usual

#### Scenario: Manual override still records telemetry

- **WHEN** `state.manual_override_active` is true during a tick
- **THEN** execution-history and slot-observation recording SHALL still run for that tick

### Requirement: EV charger control obeys manual override and force_stop

EV charger switching SHALL consult manual-override and quick-action state, not only `ev_charger_plans`. Under manual override the executor SHALL NOT write the EV charger switch. Under the `force_stop` quick action the executor SHALL command the EV charger off, even if the slot plan schedules charging.

#### Scenario: force_stop stops a planned EV charge

- **WHEN** a `force_stop` quick action is active
- **AND** the current slot's `ev_charger_plans` schedules charging for a charger
- **THEN** the executor SHALL command that EV charger switch off

#### Scenario: Manual override leaves the EV charger untouched

- **WHEN** `state.manual_override_active` is true
- **THEN** the executor SHALL NOT write the EV charger switch state

#### Scenario: Normal operation follows the EV plan

- **WHEN** no manual override and no `force_stop` quick action are active
- **THEN** the executor SHALL control the EV charger per the slot's `ev_charger_plans`, as before

### Requirement: Executor rejects a stale schedule and holds

Before acting on the loaded schedule, the executor SHALL compare the schedule's generation time to the current time. If the schedule is older than `executor.max_schedule_age_hours` (optional config, default 6), the executor SHALL NOT execute it: it SHALL emit a warning via the existing system-alert path and fall back to the slot-failure hold behavior (`grid_charging=False`, `soc_target` = current SoC).

#### Scenario: Stale schedule triggers hold and alert

- **WHEN** the loaded schedule's generation time is older than `max_schedule_age_hours`
- **THEN** the executor SHALL emit a warning via the system-alert path
- **AND** the executor SHALL apply the hold fallback (`grid_charging=False`, `soc_target` = current SoC)
- **AND** the executor SHALL NOT apply the stale schedule's planned actions

#### Scenario: Fresh schedule executes normally

- **WHEN** the loaded schedule's generation time is within `max_schedule_age_hours`
- **THEN** the executor SHALL execute the schedule as planned

#### Scenario: Threshold is configurable with a default

- **WHEN** `executor.max_schedule_age_hours` is not set in config
- **THEN** the executor SHALL use a default of 6 hours for the freshness check

### Requirement: EV charge current is derived from nominal battery voltage

When the charger is controlled in Amps, the executor SHALL convert a planned charge power (kW) to an Ampere setpoint using the configured `nominal_voltage_v`, not the worst-case `min_voltage_v`. `min_voltage_v` SHALL be used only for safety limits, not for the kW→A conversion.

#### Scenario: kW→A conversion uses nominal voltage

- **WHEN** the charger is in Ampere-control mode and a slot plans `P` kW
- **THEN** the commanded current equals `(P × 1000) / nominal_voltage_v`
- **AND** `min_voltage_v` is not used in the conversion

#### Scenario: Safety limits still use the configured current bounds

- **WHEN** the converted current exceeds the configured charge-current limit
- **THEN** it is clamped to that limit, unchanged from current behavior

### Requirement: Boost-cancellation notification is delivered

When a water boost is cancelled because SoC dropped below the configured floor, the executor SHALL deliver the cancellation notification (awaiting the async send), not create and discard the coroutine.

#### Scenario: Low-SoC boost cancellation notifies the user

- **WHEN** a water boost is cancelled because SoC fell below `min_soc + 10%`
- **THEN** the cancellation notification is sent to the configured notifier
- **AND** no "coroutine was never awaited" runtime warning is produced

### Requirement: WebSocket broadcast failures are logged, not swallowed

The executor SHALL log (at debug or warning level) when a real-time error/status WebSocket broadcast fails, instead of silently passing. The underlying record SHALL still be persisted before the broadcast is attempted.

#### Scenario: WS emit failure is logged

- **WHEN** the WebSocket manager raises during a real-time error/status broadcast
- **THEN** the failure is logged
- **AND** the error/status record remains persisted (e.g. in `recent_errors`)

### Requirement: The dead force_export quick action is removed

The executor SHALL NOT expose the `force_export` quick action. Its override type, controller branch, and engine handler are removed because it had no UI caller and hardcoded the grid-export limit to 0 W (exporting nothing). Other quick actions are unaffected.

#### Scenario: force_export is not a supported quick action

- **WHEN** a `force_export` quick action is requested
- **THEN** the executor does not treat it as a known quick action

#### Scenario: force_charge remains available

- **WHEN** a `force_charge` quick action is requested
- **THEN** it is handled exactly as before

### Requirement: Null inverter profile falls back to generic without error

When `system.inverter_profile` is null, empty, or missing (the shipped default in `config.default.yaml`), inverter profile loading SHALL resolve directly to the `generic` profile with at most an INFO-level log line, and SHALL NOT attempt to load a profile file named after the null value (e.g. `profiles/None.yaml`) or emit an ERROR-level log. An explicitly configured profile name that cannot be found SHALL keep the existing behavior: WARNING-level log and fallback to `generic`.

#### Scenario: Fresh install boots clean

- **WHEN** the application starts with the shipped default configuration (`inverter_profile: null`)
- **THEN** the `generic` profile is loaded, no attempt is made to open `profiles/None.yaml`, and no ERROR-level log line is produced by profile loading

#### Scenario: Misspelled profile still warns

- **WHEN** `system.inverter_profile` is set to a non-empty name with no matching profile file
- **THEN** a WARNING is logged and the `generic` profile is used (unchanged behavior)
