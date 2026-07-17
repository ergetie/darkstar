# Delta: Per-Device EV Scheduling

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Active goal that yields zero scheduled energy logs a warning
When a charger has an active goal (`required_kwh > 0` with a resolved deadline) and the solver returns a schedule with zero total planned energy for that charger, the pipeline SHALL log a WARNING that names the charger, the required kWh, the per-day quota split, and the minimum schedulable chunk — an active goal SHALL never silently convert entirely to shortfall.

#### Scenario: Infeasible goal is loudly reported
- **WHEN** a charger's goal cannot be scheduled at all (e.g. quota/feasibility interaction) and the solve completes
- **THEN** a WARNING SHALL be logged containing the charger ID, required kWh, quota-by-day values, and min chunk kWh

#### Scenario: Scheduled goal logs no warning
- **WHEN** a charger's goal results in any nonzero scheduled energy
- **THEN** no zero-scheduled WARNING SHALL be logged for that charger
