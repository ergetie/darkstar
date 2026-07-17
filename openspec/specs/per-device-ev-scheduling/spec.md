# Spec: Per-Device EV Scheduling

## Purpose

TBD - Defines how the system handles multiple EV chargers with independent per-device scheduling, MILP decision variables, deadline constraints, SoC tracking, and executor control.
## Requirements
### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), plus hardware facts (`sensor`, `soc_sensor`, `plug_sensor`, `battery_capacity_kwh`, `max_power_kw`, `type`, current/phase entities) and the optional HA goal entities (`ha_ready_by_entity`, `ha_target_soc_entity`).

**Goal fields do NOT live in config.** `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, and `keep_on_after_target` SHALL NOT be read from `config.yaml`; goals are owned by `data/ev_multi_day_state.json` via the dashboard/API/HA sync (see `ev-schedule-api`). If any goal field (or the legacy `departure_time` / `penalty_levels`) is present in config, the loader SHALL log a deprecation warning naming the dashboard as the place to set goals, and SHALL ignore the value for scheduling. Malformed values in these ignored fields SHALL NOT crash config loading.

**No `charge_priority` field.** Surplus-PV routing is owned by the existing `excess_pv.priority[]` list (see `excess-pv-priority-dispatch`).

#### Scenario: Config with goal fields is tolerated but ignored
- **WHEN** a charger config still contains `target_soc_percent: 90` or `departure_time: "07:00"`
- **THEN** the loader SHALL emit a deprecation warning pointing to the dashboard
- **AND** the value SHALL NOT influence scheduling (the state-file goal, or absence of one, governs)

#### Scenario: Malformed legacy goal value does not crash
- **WHEN** a charger config contains `target_soc_percent: "80%"`
- **THEN** config loading SHALL succeed with a warning (no ValueError propagation)

#### Scenario: Charger with no switch entity
- **WHEN** an enabled charger has `switch_entity: ""` or the field is absent
- **THEN** the executor SHALL skip switch control for that charger (planning-only mode)

### Requirement: Per-device MILP decision variables
The Kepler solver SHALL create separate decision variables for each plugged-in, enabled EV charger: a binary `ev_charge[d][t]` (charging on/off) and continuous `ev_energy[d][t]` (energy in kWh) indexed by device `d` and time slot `t`.

The energy link SHALL depend on the charger's control type:

- For `type: binary` chargers: `ev_energy[d][t] == ev_charge[d][t] × max_power_kw × slot_h` (full power or off, unchanged).
- For `type: current` chargers: `min_power_kw × slot_h × ev_charge[d][t] <= ev_energy[d][t] <= max_power_kw × slot_h × ev_charge[d][t]` (semi-continuous: when on, any power between the charger's minimum and maximum; when off, zero).

`min_power_kw` SHALL be derived from the charger's configured `min_current_a` and phase count (`min_current_a × 230 V × phases / 1000`), never hardcoded, and SHALL include a small upward margin (~1%) so the executor's floor-based kW→amps conversion never rounds a planned minimum below `min_current_a`. Fractional planning SHALL always apply to `type: current` chargers — there is no opt-out setting.

The binary `ev_charge[d][t]` SHALL continue to drive discharge blocking (`any_ev_charging`), surplus-charging exclusivity, and all other on/off-gated constraints for both charger types.

#### Scenario: Two plugged-in chargers get independent variables
- **WHEN** two enabled chargers are both plugged in
- **THEN** the solver SHALL create independent binary and energy variables for each charger
- **AND** each charger MAY charge in different time slots

#### Scenario: Unplugged charger gets no variables
- **WHEN** a charger is enabled but not plugged in
- **THEN** the solver SHALL NOT create decision variables for that charger
- **AND** no energy demand from that charger SHALL appear in the energy balance

#### Scenario: Single charger behaves identically to current system
- **WHEN** only one enabled `type: binary` charger is plugged in
- **THEN** the solver output SHALL be equivalent to the current single-EV model

#### Scenario: Current-type charger is planned at fractional power
- **WHEN** a `type: current` charger (max 11 kW, min_current_a 6, 3 phases) needs 2.6 kWh before a deadline spanning many cheap slots
- **THEN** the solver MAY schedule slots at less than full power (e.g. ~4.2 kW), each at or above the derived `min_power_kw`
- **AND** the total scheduled energy SHALL meet the requirement without full-power-or-nothing rounding

#### Scenario: Current-type charger never planned below its minimum amps
- **WHEN** the solver schedules any nonzero energy for a `type: current` charger in a slot
- **THEN** the implied power SHALL be at least the derived `min_power_kw`
- **AND** the executor's `planned_kw_to_amps` conversion of that power SHALL yield an amp setpoint `>= min_current_a` (no pause caused by planner rounding)

#### Scenario: Binary charger keeps full-power-or-off planning
- **WHEN** a `type: binary` charger is scheduled in a slot
- **THEN** the planned energy for that slot SHALL equal exactly `max_power_kw × slot_h`

#### Scenario: Fractional charging still blocks battery discharge
- **WHEN** a `type: current` charger is planned at partial power in slot t
- **THEN** `any_ev_charging[t]` SHALL be 1 and battery discharge SHALL be blocked in slot t (source isolation unchanged)

### Requirement: Active goal that yields zero scheduled energy logs a warning
When a charger has an active goal (`required_kwh > 0` with a resolved deadline) and the solver returns a schedule with zero total planned energy for that charger, the pipeline SHALL log a WARNING that names the charger, the required kWh, the per-day quota split, and the minimum schedulable chunk — an active goal SHALL never silently convert entirely to shortfall.

#### Scenario: Infeasible goal is loudly reported
- **WHEN** a charger's goal cannot be scheduled at all (e.g. quota/feasibility interaction) and the solve completes
- **THEN** a WARNING SHALL be logged containing the charger ID, required kWh, quota-by-day values, and min chunk kWh

#### Scenario: Scheduled goal logs no warning
- **WHEN** a charger's goal results in any nonzero scheduled energy
- **THEN** no zero-scheduled WARNING SHALL be logged for that charger

### Requirement: Per-device deadline constraints
The solver SHALL enforce a per-device deadline constraint: for each charger with a deadline, `ev_energy[d][t] == 0` for all slots where the slot end time exceeds that charger's deadline.

#### Scenario: Charger with early deadline stops before late charger
- **WHEN** charger A has deadline 07:00 and charger B has deadline 09:00
- **THEN** charger A SHALL have zero charging in all slots ending after 07:00
- **AND** charger B MAY still charge in slots between 07:00 and 09:00

### Requirement: Per-device discharge blocking
The solver SHALL enforce discharge blocking when ANY charger is charging: `discharge[t] <= (1 - any_ev_charging[t]) * M` where `any_ev_charging[t]` is 1 if any charger is active in slot t.

#### Scenario: One charger active blocks discharge
- **WHEN** charger A is charging in slot t and charger B is not
- **THEN** battery discharge SHALL be zero in slot t

#### Scenario: No chargers active allows normal discharge
- **WHEN** no charger is charging in slot t
- **THEN** battery discharge SHALL be bounded only by its normal upper bound

### Requirement: Shared grid import budget
All EV chargers SHALL share the grid import budget. The energy balance constraint SHALL sum all chargers' energy: `load + sum(ev_energy[d][t] for d) + water + charge == pv + discharge + grid_import`. The existing `max_import_power_kw` constraint naturally limits combined consumption.

#### Scenario: Two chargers cannot exceed grid fuse
- **WHEN** charger A wants 11 kW and charger B wants 7.4 kW (total 18.4 kW)
- **AND** `max_import_power_kw` is 16 kW and house load is 2 kW
- **THEN** the solver SHALL NOT schedule both at full power simultaneously
- **AND** the solver SHALL stagger or reduce charging to respect the 16 kW import limit

### Requirement: Per-device schedule output
The schedule output SHALL include a per-device `ev_chargers` dict in each slot, mapping charger ID to `{charging_kw: float}`. The aggregate `ev_charging_kw` field SHALL remain as the sum of all chargers for backward compatibility.

#### Scenario: Schedule includes per-device breakdown
- **WHEN** the solver plans charger A at 11 kW and charger B at 7.4 kW in a slot
- **THEN** the schedule slot SHALL contain `ev_chargers: {"ev_charger_1": {"charging_kw": 11.0}, "ev_charger_2": {"charging_kw": 7.4}}`
- **AND** `ev_charging_kw` SHALL be `18.4`

#### Scenario: Schedule with no EV charging
- **WHEN** no chargers are scheduled in a slot
- **THEN** `ev_chargers` SHALL be an empty dict or contain entries with `charging_kw: 0.0`
- **AND** `ev_charging_kw` SHALL be `0.0`

### Requirement: Per-device executor control loop
The executor SHALL iterate over all enabled chargers with a control entity configured (`switch_entity` for `type: binary`, `current_entity` for `type: current`). For each binary charger, the executor SHALL independently decide whether to turn the switch on or off based on that charger's entry in the schedule's `ev_chargers` dict. For each current-type charger, the executor SHALL compute an ampere setpoint from that charger's planned kW (subject to load-balancer capping when enabled) and write it to the `current_entity`.

#### Scenario: Two chargers controlled independently
- **WHEN** the schedule has charger A at 11 kW and charger B at 0 kW in the current slot
- **THEN** the executor SHALL turn ON charger A's switch entity (binary) or write its ampere setpoint (current)
- **AND** the executor SHALL turn OFF (or leave off) charger B

#### Scenario: Charger not in schedule is left off
- **WHEN** a charger has a control entity but no entry in the current slot's `ev_chargers` dict
- **THEN** the executor SHALL leave that charger in its current state (default: off)

#### Scenario: Binary and current chargers coexist
- **WHEN** one enabled charger is `type: binary` and another is `type: current`, both scheduled
- **THEN** each SHALL be actuated via its own mechanism in the same tick

### Requirement: Per-device executor state tracking
The executor SHALL maintain independent state per charger: charging active flag, start time, slot end time, zero-power tick count, and failure notification flag. Each charger's safety timeout (30-minute max overrun) SHALL operate independently.

#### Scenario: One charger times out while another continues
- **WHEN** charger A has been charging for 30 minutes past its scheduled slot end
- **AND** charger B is still within its scheduled slot
- **THEN** the executor SHALL force-stop charger A
- **AND** charger B SHALL continue charging normally

#### Scenario: Fresh state on config reload
- **WHEN** the executor config is reloaded
- **THEN** the executor SHALL rebuild its per-device state dict from the new charger list
- **AND** chargers removed from config SHALL have their state dropped

### Requirement: Per-device source isolation
The executor SHALL block battery discharge when ANY enabled charger is either scheduled to charge or detected as actually charging. The source isolation logic SHALL check across all chargers.

#### Scenario: Unscheduled charger drawing power triggers isolation
- **WHEN** charger A is not scheduled but is physically drawing 5 kW
- **AND** charger B is idle
- **THEN** battery discharge SHALL still be blocked (source isolation active)

### Requirement: Per-device EV power detection
The executor SHALL read power from each enabled charger's sensor independently via the LoadDisaggregator. The total EV power for source isolation purposes SHALL be the sum across all chargers.

#### Scenario: Multiple chargers contribute to total EV power
- **WHEN** charger A draws 11 kW and charger B draws 7 kW
- **THEN** the executor SHALL detect total EV power as 18 kW
- **AND** source isolation SHALL be active

### Requirement: EV charger with invalid power is registered as disabled
The load registration service SHALL register EV chargers configured with `max_power_kw <= 0` (or missing `max_power_kw` entirely) as visible-but-disabled. The charger SHALL appear in the load registry with a `disabled_reason` of `"missing_power_kw"` so it remains visible in the UI and health surfaces. The planner's adapter SHALL exclude such chargers when building `KeplerConfig.ev_chargers`, and the solver SHALL NOT create decision variables for them.

A `HealthIssue` with `category="ev"`, `severity="critical"`, and `code="EV_MISSING_POWER"` SHALL be emitted for each such charger. The issue's `entity_id` SHALL be the charger ID, and `details` SHALL include the charger ID and the observed `max_power_kw` value.

This requirement SHALL apply equally when `max_power_kw` is entirely absent from the config (previously defaulted silently to `0.0` by `backend/loads/service.py`).

#### Scenario: Missing max_power_kw registers as disabled
- **GIVEN** an EV charger config entry with `enabled: true` and no `max_power_kw` field
- **WHEN** the load service loads configuration
- **THEN** the charger is registered with `disabled_reason="missing_power_kw"`
- **AND** the charger appears in the load registry
- **AND** a `HealthIssue` is emitted with category `ev`, severity `critical`, code `EV_MISSING_POWER`, and `entity_id` set to the charger ID

#### Scenario: Zero max_power_kw registers as disabled
- **GIVEN** an EV charger config entry with `enabled: true` and `max_power_kw: 0`
- **WHEN** the load service loads configuration
- **THEN** the charger is registered with `disabled_reason="missing_power_kw"`
- **AND** the planner's adapter excludes the charger from `KeplerConfig.ev_chargers`
- **AND** the solver does not create decision variables for the charger

#### Scenario: Valid max_power_kw registers normally
- **GIVEN** an EV charger config entry with `max_power_kw: 11.0`
- **WHEN** the load service loads configuration
- **THEN** the charger is registered without a `disabled_reason`
- **AND** no `EV_MISSING_POWER` HealthIssue is emitted for that charger

#### Scenario: Disabled-state charger is visible in UI
- **WHEN** the frontend fetches the load registry
- **THEN** a charger with `disabled_reason="missing_power_kw"` is included in the response
- **AND** the response field `disabled_reason` is set to `"missing_power_kw"` for that entry

#### Scenario: Fixing config re-enables charger without restart
- **GIVEN** a charger was registered with `disabled_reason="missing_power_kw"`
- **WHEN** the user updates `max_power_kw` to a positive value and the config is reloaded
- **THEN** the charger is re-registered without a `disabled_reason`
- **AND** the corresponding `EV_MISSING_POWER` HealthIssue is cleared
- **AND** the next planner run includes the charger in `KeplerConfig.ev_chargers`

### Requirement: Per-device ready-by resolution
The pipeline SHALL resolve each charger's next ready-by datetime independently from its state-file goal (`ready_by` + `repeat`, `n_days` when `repeat: every_n_days`, or `ready_by_date` when `repeat: none`). Resolution SHALL use **one shared resolver function** used identically by the planner pipeline, the schedule API, and the HA sync — divergent duplicate implementations are a defect. The shared resolver SHALL default `n_days` to 1 and SHALL anchor the `every_n_days` cycle to the goal's `last_updated` date (deterministic and user-controllable by re-saving), not a hard-coded epoch. A missing/null `repeat` SHALL be treated as `daily` (never string-matched against `"none"`). This resolved datetime SHALL be used as the Kepler deadline for that charger. A charger past a non-repeating ready-by datetime SHALL have no deadline (inert).

#### Scenario: Daily repeat resolves to the next occurrence
- **WHEN** `ready_by: "07:00"`, `repeat: daily`, and the current time is 22:00
- **THEN** the resolved deadline SHALL be tomorrow 07:00

#### Scenario: Every-N-days repeat
- **WHEN** `repeat: every_n_days`, `n_days: 3`, and the goal was last saved today
- **THEN** the resolved deadline SHALL be the `ready_by` time 3 days from the save date, and every 3 days thereafter
- **AND** the API, planner, and HA sync SHALL all resolve the same datetime

#### Scenario: One-off date in the future
- **WHEN** `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, and today is 2026-06-08
- **THEN** the resolved deadline SHALL be 2026-06-12 07:00

#### Scenario: One-off date already passed
- **WHEN** `repeat: none` and the `ready_by_date`/`ready_by` datetime is in the past
- **THEN** the charger SHALL have no deadline and SHALL NOT be scheduled

#### Scenario: Null repeat from a legacy state file
- **WHEN** a state-file goal has `repeat: null`
- **THEN** the resolver SHALL treat it as `daily` (not as the one-off `"none"` mode)

### Requirement: Per-device EV config supports optional HA goal entities
Each entry in `ev_chargers[]` SHALL support two optional fields: `ha_ready_by_entity` (string, HA `input_datetime` entity ID) and `ha_target_soc_entity` (string, HA `input_number` entity ID). When configured, the backend SHALL sync the charger's ready-by time and target SoC bidirectionally with those entities, and HA values SHALL take priority over the dashboard value when set. (The core goal fields — `target_soc_percent`, `ready_by`, `repeat`, `keep_on_after_target` — are defined by the `per-device-ev-scheduling` change in Module 4. **No `charge_priority`** — surplus ordering is owned by `excess_pv.priority[]`.)

#### Scenario: Charger with HA goal entities configured
- **WHEN** a charger has `ha_ready_by_entity: "input_datetime.ev_ready_by"` and `ha_target_soc_entity: "input_number.ev_target_soc"`
- **THEN** the config loader SHALL store both entity IDs
- **AND** the backend SHALL subscribe to state changes for both

#### Scenario: Charger without HA goal entities
- **WHEN** a charger has neither field (or they are empty/null)
- **THEN** no HA subscription SHALL be created for the goal
- **AND** the charger SHALL operate using the dashboard-managed goal only

#### Scenario: HA value overrides the dashboard value
- **WHEN** both an HA goal entity and a dashboard-set value exist for the same field
- **THEN** the HA value SHALL take precedence (mirroring the vacation-mode override)
