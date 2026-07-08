# Spec: Per-Device EV Scheduling

## Purpose

TBD - Defines how the system handles multiple EV chargers with independent per-device scheduling, MILP decision variables, deadline constraints, SoC tracking, and executor control.
## Requirements
### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), and the goal fields below. The goal fields replace the prior `departure_time` + `penalty_levels` model.

Goal fields:
- `target_soc_percent` (int, 0–100, default 80) — the SoC the vehicle should reach.
- `ready_by` (string, `HH:MM` 24h) — the time the target should be met by.
- `repeat` (enum `daily` | `weekdays` | `weekends` | `every_n_days` | `none`, default `daily`) — how the ready-by time recurs. `none` = a one-off.
- `n_days` (int) — used when `repeat: every_n_days`.
- `ready_by_date` (string, ISO date) — used when `repeat: none` (the specific date for the one-off).
- `keep_on_after_target` (boolean, default false) — keep the switch ON through the ready-by time after the target is met.

**No `charge_priority` field.** Surplus-PV routing is owned by the existing `excess_pv.priority[]` list (see `excess-pv-priority-dispatch`); the home battery is implicitly first via `soc_threshold_percent`. Adding a per-charger switch here would duplicate or contradict that surface.

`penalty_levels` is **retired**: if present it SHALL be ignored for scheduling, SHALL emit a one-release deprecation warning, and SHALL be auto-migrated to `target_soc_percent` equal to the highest configured `max_soc`. `departure_time` SHALL be accepted as a deprecated alias for `ready_by` (with a warning). The config loader SHALL use a YAML 1.2 parser (ruamel.yaml) so unquoted `HH:MM` values read as strings, and SHALL accept the time as either `"HH:MM"` or an integer minutes-since-midnight (0–1439), converting integers to `"HH:MM"`; out-of-range values SHALL be treated as invalid.

#### Scenario: Charger with a daily goal
- **WHEN** a charger has `target_soc_percent: 80`, `ready_by: "07:00"`, `repeat: daily`
- **THEN** the pipeline SHALL aim to reach 80% by the next 07:00 and repeat every day

#### Scenario: Charger with a one-off date
- **WHEN** a charger has `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, `target_soc_percent: 100`
- **THEN** the pipeline SHALL aim to reach 100% by 2026-06-12 07:00 and SHALL become inert after that datetime passes

#### Scenario: Legacy penalty_levels present
- **WHEN** a charger config still contains `penalty_levels`
- **THEN** the loader SHALL ignore them for scheduling, emit a deprecation warning, and set `target_soc_percent` to the highest configured `max_soc`

#### Scenario: Legacy departure_time alias
- **WHEN** a charger config uses `departure_time: "07:00"` and no `ready_by`
- **THEN** the loader SHALL treat `07:00` as `ready_by` and emit a deprecation warning

#### Scenario: Charger with no switch entity
- **WHEN** an enabled charger has `switch_entity: ""` or the field is absent
- **THEN** the executor SHALL skip switch control for that charger (planning-only mode)

#### Scenario: Unquoted HH:MM in config.yaml read correctly
- **WHEN** config.yaml contains `ready_by: 16:00` (unquoted)
- **THEN** the YAML 1.2 parser SHALL read it as the string `"16:00"` (not the integer `960`)

### Requirement: Per-device MILP decision variables
The Kepler solver SHALL create separate decision variables for each plugged-in, enabled EV charger: a binary `ev_charge[d][t]` (charging on/off) and continuous `ev_energy[d][t]` (energy in kWh) indexed by device `d` and time slot `t`.

#### Scenario: Two plugged-in chargers get independent variables
- **WHEN** two enabled chargers are both plugged in
- **THEN** the solver SHALL create independent binary and energy variables for each charger
- **AND** each charger MAY charge in different time slots

#### Scenario: Unplugged charger gets no variables
- **WHEN** a charger is enabled but not plugged in
- **THEN** the solver SHALL NOT create decision variables for that charger
- **AND** no energy demand from that charger SHALL appear in the energy balance

#### Scenario: Single charger behaves identically to current system
- **WHEN** only one enabled charger is plugged in
- **THEN** the solver output SHALL be equivalent to the current single-EV model

### Requirement: Per-device deadline constraints
The solver SHALL enforce a per-device deadline constraint: for each charger with a deadline, `ev_energy[d][t] == 0` for all slots where the slot end time exceeds that charger's deadline.

#### Scenario: Charger with early deadline stops before late charger
- **WHEN** charger A has deadline 07:00 and charger B has deadline 09:00
- **THEN** charger A SHALL have zero charging in all slots ending after 07:00
- **AND** charger B MAY still charge in slots between 07:00 and 09:00

### Requirement: Per-device SoC and incentive bucket constraints
The solver SHALL track per-device incentive buckets based on each charger's `battery_capacity_kwh`, current `soc_percent`, and `penalty_levels`. Each charger's total energy charged SHALL equal the sum of its bucket allocations.

#### Scenario: Two chargers with different SoC levels
- **WHEN** charger A is at 20% SoC (high incentive to charge) and charger B is at 80% SoC (low incentive)
- **THEN** the solver SHALL prioritize charging charger A over charger B when grid import is constrained

#### Scenario: Charger with no penalty levels uses default bucket
- **WHEN** a charger has empty `penalty_levels`
- **THEN** the solver SHALL create a single bucket covering 0-100% SoC with zero penalty (charge whenever cost-effective)

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
The pipeline SHALL resolve each charger's next ready-by datetime independently from its `ready_by` + `repeat` (or `ready_by_date` when `repeat: none`). This resolved datetime SHALL be used as the Kepler deadline for that charger. A charger past a non-repeating ready-by datetime SHALL have no deadline (inert).

#### Scenario: Daily repeat resolves to the next occurrence
- **WHEN** `ready_by: "07:00"`, `repeat: daily`, and the current time is 22:00
- **THEN** the resolved deadline SHALL be tomorrow 07:00

#### Scenario: Every-N-days repeat
- **WHEN** `repeat: every_n_days`, `n_days: 2`, and today is not a charging day
- **THEN** the resolved deadline SHALL be the `ready_by` time on the next matching day

#### Scenario: One-off date in the future
- **WHEN** `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, and today is 2026-06-08
- **THEN** the resolved deadline SHALL be 2026-06-12 07:00

#### Scenario: One-off date already passed
- **WHEN** `repeat: none` and the `ready_by_date`/`ready_by` datetime is in the past
- **THEN** the charger SHALL have no deadline and SHALL NOT be scheduled

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
