# Spec: Per-Device EV Scheduling

## Purpose

TBD - Defines how the system handles multiple EV chargers with independent per-device scheduling, MILP decision variables, deadline constraints, SoC tracking, and executor control.

## Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `departure_time` (string, HH:MM 24h format), `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), `type` (string, `binary` (default) or `current`), `current_entity` (string, HA number entity ID for the ampere setpoint, required when `type: current`), `min_current_a` (integer, default 6), `max_current_a` (integer, required when `type: current`), and `phases` (list of phase numbers the charger is wired to, e.g. `[1, 2, 3]`). These fields replace the global `ev_departure_time` and `executor.ev_charger.*` settings.

The config loader SHALL use a YAML 1.2 parser (ruamel.yaml) to read `config.yaml`, ensuring that unquoted `HH:MM` values are read as strings, not as YAML 1.1 sexagesimal integers.

The config loader SHALL accept `departure_time` as either a string in `"HH:MM"` format or an integer representing minutes since midnight (0–1439). If an integer is provided, it SHALL be converted to `"HH:MM"` format (e.g., `960` → `"16:00"`). Values outside 0–1439 SHALL be treated as invalid and result in `None`.

#### Scenario: Two chargers with different departure times
- **WHEN** `ev_chargers` contains charger "tesla" with `departure_time: "07:00"` and charger "leaf" with `departure_time: "08:30"`
- **THEN** the planner SHALL use 07:00 as the deadline for tesla and 08:30 as the deadline for leaf

#### Scenario: Charger with no departure time
- **WHEN** an enabled charger has `departure_time: ""` or the field is absent
- **THEN** the planner SHALL not apply a deadline constraint for that charger (charge whenever cheapest)

#### Scenario: Charger with no control entity
- **WHEN** an enabled charger has neither a `switch_entity` nor a `current_entity` configured
- **THEN** the executor SHALL skip actuation for that charger (planning-only mode)

#### Scenario: Current-type charger without current_entity is invalid
- **WHEN** a charger has `type: current` but no `current_entity`
- **THEN** config validation SHALL flag the device with an actionable error

#### Scenario: Departure time stored as YAML 1.1 sexagesimal integer
- **WHEN** `departure_time` is read from config as the integer `960` (due to prior YAML 1.1 parsing of `16:00`)
- **THEN** the config loader SHALL convert it to the string `"16:00"`
- **AND** the planner SHALL use 16:00 as the deadline for that charger

#### Scenario: Departure time stored as out-of-range integer
- **WHEN** `departure_time` is read from config as an integer outside 0–1439 (e.g., `9999`)
- **THEN** the config loader SHALL treat it as invalid and return `None`
- **AND** the planner SHALL not apply a deadline constraint for that charger

#### Scenario: Unquoted HH:MM in config.yaml read correctly
- **WHEN** config.yaml contains `departure_time: 16:00` (unquoted)
- **THEN** the YAML 1.2 parser SHALL read it as the string `"16:00"` (not the integer `960`)
- **AND** the planner SHALL use 16:00 as the deadline

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
