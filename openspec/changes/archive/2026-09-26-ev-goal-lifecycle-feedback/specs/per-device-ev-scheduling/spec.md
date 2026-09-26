## MODIFIED Requirements

### Requirement: Per-device ready-by resolution
The pipeline SHALL resolve each charger's next ready-by datetime independently from its state-file goal (`ready_by` + `repeat`, `n_days` when `repeat: every_n_days`, or `ready_by_date` when `repeat: none`). Resolution SHALL use **one shared resolver function** used identically by the planner pipeline, the schedule API, and the HA sync — divergent duplicate implementations are a defect. The shared resolver SHALL default `n_days` to 1 and SHALL anchor the `every_n_days` cycle to the goal's `anchor_date`, falling back to the local date of `last_updated` only for legacy goals without an `anchor_date` (the fallback value SHALL be persisted as `anchor_date` by the next goal write so the cycle is locked), not a hard-coded epoch. A missing/null `repeat` SHALL be treated as `daily` (never string-matched against `"none"`). This resolved datetime SHALL be used as the Kepler deadline for that charger. A charger past a non-repeating ready-by datetime SHALL have no deadline (inert). Resolution SHALL apply to chargers with an active goal whether or not they are currently plugged in.

#### Scenario: Daily repeat resolves to the next occurrence
- **WHEN** `ready_by: "07:00"`, `repeat: daily`, and the current time is 22:00
- **THEN** the resolved deadline SHALL be tomorrow 07:00

#### Scenario: Every-N-days repeat
- **WHEN** `repeat: every_n_days`, `n_days: 3`, and `anchor_date` is today
- **THEN** the resolved deadline SHALL be the `ready_by` time 3 days from the anchor date, and every 3 days thereafter
- **AND** the API, planner, and HA sync SHALL all resolve the same datetime

#### Scenario: Anchor unaffected by unrelated writes
- **WHEN** an every-3-days goal has `anchor_date` 2026-09-20 and its `last_updated` is rewritten on 2026-09-25 by an HA change
- **THEN** the resolved deadlines SHALL still fall on 2026-09-23, 2026-09-26, …

#### Scenario: Legacy goal without an anchor
- **WHEN** an every-N-days goal has no `anchor_date`
- **THEN** the resolver SHALL use the local date of `last_updated`
- **AND** the next goal write SHALL persist that date as `anchor_date`

#### Scenario: One-off date in the future
- **WHEN** `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, and today is 2026-06-08
- **THEN** the resolved deadline SHALL be 2026-06-12 07:00

#### Scenario: One-off date already passed
- **WHEN** `repeat: none` and the `ready_by_date`/`ready_by` datetime is in the past
- **THEN** the charger SHALL have no deadline and SHALL NOT be scheduled

#### Scenario: Null repeat from a legacy state file
- **WHEN** a state-file goal has `repeat: null`
- **THEN** the resolver SHALL treat it as `daily` (not as the one-off `"none"` mode)

#### Scenario: Unplugged charger with a goal
- **WHEN** a charger with a daily 07:00 goal is unplugged at 22:00
- **THEN** its deadline SHALL still resolve to tomorrow 07:00

### Requirement: Per-device MILP decision variables
The Kepler solver SHALL create separate decision variables for each enabled EV charger that is plugged in, and for each enabled EV charger that is unplugged but has an active goal with a resolved deadline and a known last SoC ("assumed plugged"): a binary `ev_charge[d][t]` (charging on/off) and continuous `ev_energy[d][t]` (energy in kWh) indexed by device `d` and time slot `t`. Assumed-plugged chargers SHALL NOT receive surplus-charging variables. Their goal requirement SHALL be modelled exactly as for a plugged charger with a goal (in-horizon scheduled energy plus post-horizon deferral tiers plus shortfall, per `ev-deferral-value`); only surplus energy is absent from it. Their scheduled energy SHALL count in the energy balance and grid import budget like any other charger, and their results SHALL be marked `assumed_plugged: true` in the per-charger schedule output.

The energy link SHALL depend on the charger's control type:

- For `type: binary` chargers: `ev_energy[d][t] == ev_charge[d][t] × max_power_kw × slot_h` (full power or off, unchanged).
- For `type: current` chargers: `min_power_kw × slot_h × ev_charge[d][t] <= ev_energy[d][t] <= max_power_kw × slot_h × ev_charge[d][t]` (semi-continuous: when on, any power between the charger's minimum and maximum; when off, zero).

`min_power_kw` SHALL be derived from the charger's configured `min_current_a` and phase count (`min_current_a × 230 V × phases / 1000`), never hardcoded, and SHALL include a small upward margin (~1%) so the executor's floor-based kW→amps conversion never rounds a planned minimum below `min_current_a`. Fractional planning SHALL always apply to `type: current` chargers — there is no opt-out setting.

The binary `ev_charge[d][t]` SHALL continue to drive discharge blocking (`any_ev_charging`), surplus-charging exclusivity, and all other on/off-gated constraints for both charger types.

#### Scenario: Two plugged-in chargers get independent variables
- **WHEN** two enabled chargers are both plugged in
- **THEN** the solver SHALL create independent binary and energy variables for each charger
- **AND** each charger MAY charge in different time slots

#### Scenario: Unplugged charger without a goal gets no variables
- **WHEN** a charger is enabled but not plugged in and has no active goal
- **THEN** the solver SHALL NOT create decision variables for that charger
- **AND** no energy demand from that charger SHALL appear in the energy balance

#### Scenario: Unplugged charger with a goal is planned as assumed plugged
- **WHEN** a charger is enabled, unplugged, has an active goal with a resolved deadline and a last known SoC
- **THEN** the solver SHALL create scheduled-charging variables for it but no surplus variables
- **AND** deferral tiers SHALL be built for it when its deadline is beyond the horizon, as for a plugged charger
- **AND** its results SHALL be marked `assumed_plugged: true`

#### Scenario: Unplugged charger with a goal but no known SoC
- **WHEN** a charger is unplugged with an active goal and no live or persisted SoC is available
- **THEN** the solver SHALL NOT create variables for that charger

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

## ADDED Requirements

### Requirement: Executor ignores planned charging for chargers that are not plugged in
The executor SHALL use a charger's planned EV kW, keep-on flag and surplus flag for switch control and source isolation only while the charger's live plug state is connected. When the plug state is disconnected or unknown, planned charging for that charger SHALL NOT switch the charger on and SHALL NOT block battery discharge. The measured-EV-draw fail-safe for source isolation and manual-charge handling SHALL be unaffected.

#### Scenario: Assumed-plugged slot while the car is away
- **WHEN** the current slot plans 7 kW for a charger that is unplugged
- **THEN** the executor SHALL NOT switch the charger on
- **AND** SHALL NOT block battery discharge on account of that planned charging

#### Scenario: Car plugged in during a planned slot
- **WHEN** the car is plugged in during a slot with planned charging
- **THEN** the executor SHALL act on the plan from the next tick (the plug-in replan then refreshes the plan with real state)

#### Scenario: Plug state unknown
- **WHEN** the charger's plug state cannot be read
- **THEN** planned charging SHALL be treated as not actionable for that charger
- **AND** measured EV draw above threshold SHALL still block battery discharge
