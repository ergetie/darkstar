## Purpose

The Kepler solver SHALL support per-device water heater scheduling, creating independent MILP decision variables and constraints for each enabled water heater. This enables multi-heater households to schedule heating independently while sharing the grid import budget.

## Requirements

### Requirement: Per-device MILP decision variables for water heaters
The Kepler solver SHALL create separate decision variables for each enabled water heater: a binary `water_heat[d][t]` (heating on/off) and a binary `water_start[d][t]` (block start detection) indexed by device `d` and time slot `t`. Only enabled heaters with `power_kw > 0` SHALL get variables.

#### Scenario: Two enabled heaters get independent variables
- **WHEN** two enabled water heaters are configured with power_kw > 0
- **THEN** the solver SHALL create independent binary heating variables for each heater
- **AND** each heater MAY heat in different time slots

#### Scenario: Disabled heater gets no variables
- **WHEN** a water heater has `enabled: false`
- **THEN** the solver SHALL NOT create decision variables for that heater
- **AND** no energy demand from that heater SHALL appear in the energy balance

#### Scenario: Single heater behaves identically to current system
- **WHEN** only one enabled water heater is configured
- **THEN** the solver output SHALL be equivalent to the current single-heater model

### Requirement: Per-device daily minimum energy constraint
The solver SHALL enforce a per-device daily minimum energy constraint for each heater: `sum(water_heat[d][t] * power_kw * h for t in day_slots) >= min_kwh_per_day - heated_today_kwh - violation[d]`. The violation variable is penalized by the global `water_reliability_penalty_sek`.

#### Scenario: Two heaters with different daily requirements
- **WHEN** heater A has `min_kwh_per_day: 6.0` and heater B has `min_kwh_per_day: 4.0`
- **THEN** the solver SHALL enforce 6.0 kWh minimum for heater A and 4.0 kWh minimum for heater B independently

#### Scenario: Heater with today's progress deducted
- **WHEN** heater A has `min_kwh_per_day: 6.0` and has already heated 3.0 kWh today
- **THEN** the solver SHALL require at least 3.0 kWh more for heater A

#### Scenario: Smart deferral applies per-device
- **WHEN** `defer_up_to_hours: 6` is configured globally
- **THEN** each heater's daily minimum constraint SHALL extend into the early morning hours of the next day independently

### Requirement: Per-device block duration constraint
The solver SHALL enforce a per-device maximum block duration using a sliding window: for each heater `d`, `sum(water_heat[d][t:t+window]) <= max_block_slots + overshoot[d]`. The window size is determined by the global `max_block_hours` setting.

#### Scenario: Two heaters with different block patterns
- **WHEN** heater A is scheduled for a 2-hour block and heater B needs a 1.5-hour block
- **THEN** the solver SHALL allow each heater's blocks up to the max block duration independently

### Requirement: Per-device spacing constraint
The solver SHALL enforce a per-device minimum spacing between block starts: for each heater `d`, `sum(water_start[d][t:t+spacing_window]) <= 1`. The spacing window is determined by each heater's `min_spacing_hours`.

#### Scenario: Two heaters with different spacing requirements
- **WHEN** heater A has `water_min_spacing_hours: 4` and heater B has `water_min_spacing_hours: 6`
- **THEN** heater A's block starts SHALL be at least 4 hours apart
- **AND** heater B's block starts SHALL be at least 6 hours apart

#### Scenario: Heaters can start blocks at the same time
- **WHEN** heater A and heater B both have cheap slots available at 03:00
- **THEN** the solver MAY schedule both heaters to start heating at 03:00
- **AND** this does NOT violate either heater's spacing constraint (spacing is per-device, not cross-device)

### Requirement: Per-device mid-block locking
The solver SHALL support per-device mid-block locking: `water_heat[d][t] == 1` for specific slot indices per heater. The pipeline SHALL detect which heaters are currently in an active heating block and lock only those heaters' slots.

#### Scenario: One heater mid-block, another idle
- **WHEN** heater A is currently in a heating block (detected via power sensor)
- **AND** heater B is idle
- **THEN** the solver SHALL force heater A's current and remaining block slots ON
- **AND** heater B SHALL have no forced-ON slots

### Requirement: Per-device block start penalty
The solver objective SHALL include a per-device block start penalty: `sum(water_start[d][t] * block_start_penalty_sek for d, t)`. The penalty value is the global `water_block_start_penalty_sek`.

#### Scenario: Penalty discourages frequent starts per heater
- **WHEN** `block_start_penalty_sek: 3.0` and two heaters are configured
- **THEN** each block start for either heater incurs a 3.0 SEK penalty in the objective
- **AND** the solver prefers consolidated heating blocks for each heater

### Requirement: Shared grid import budget for water heaters
All water heaters SHALL share the grid import budget. The energy balance constraint SHALL sum all heaters' energy: `load + sum(water_heat[d][t] * power_kw[d] * h for d) + ev_energy + charge == pv + discharge + grid_import`. The existing `max_import_power_kw` constraint naturally limits combined consumption.

#### Scenario: Two heaters cannot exceed grid fuse
- **WHEN** heater A consumes 3 kW and heater B consumes 3 kW (total 6 kW)
- **AND** `max_import_power_kw` is 16 kW and house load is 12 kW
- **THEN** the solver SHALL NOT schedule both heaters simultaneously (12 + 6 = 18 > 16)
- **AND** the solver SHALL stagger heating to respect the 16 kW import limit

### Requirement: Per-device schedule output for water heaters
The schedule output SHALL include a per-device `water_heaters` dict in each slot, mapping heater ID to `{heating_kw: float}`. The aggregate `water_heating_kw` field SHALL remain as the sum of all heaters for backward compatibility.

#### Scenario: Schedule includes per-device breakdown
- **WHEN** the solver plans heater A at 3 kW and heater B at 3 kW in a slot
- **THEN** the schedule slot SHALL contain `water_heaters: {"main_tank": {"heating_kw": 3.0}, "upstairs_tank": {"heating_kw": 3.0}}`
- **AND** `water_heating_kw` SHALL be `6.0`

#### Scenario: Schedule with no water heating
- **WHEN** no heaters are scheduled in a slot
- **THEN** `water_heaters` SHALL be an empty dict or contain entries with `heating_kw: 0.0`
- **AND** `water_heating_kw` SHALL be `0.0`

### Requirement: Per-device executor control loop for water heaters
The executor SHALL iterate over all enabled heaters with a `target_entity` configured. For each heater, the executor SHALL independently decide whether to set the target temperature to `temp_normal` (heating) or `temp_off` (idle) based on that heater's entry in the schedule's `water_heaters` dict.

#### Scenario: Two heaters controlled independently
- **WHEN** the schedule has heater A at 3 kW and heater B at 0 kW in the current slot
- **THEN** the executor SHALL set heater A's target entity to `temp_normal`
- **AND** the executor SHALL set heater B's target entity to `temp_off`

#### Scenario: Heater not in schedule uses idle temperature
- **WHEN** a heater has a target_entity but no entry in the current slot's `water_heaters` dict
- **THEN** the executor SHALL set that heater to `temp_off`

#### Scenario: Heater without target_entity is skipped
- **WHEN** an enabled heater has `target_entity: ""` or the field is absent
- **THEN** the executor SHALL skip temperature control for that heater (planning-only mode)

### Requirement: Per-device WaterHeaterInput dataclass
The adapter SHALL create a `WaterHeaterInput` dataclass for each enabled water heater and pass a list to the Kepler solver. The dataclass SHALL contain per-device fields: `id`, `power_kw`, `min_kwh_per_day`, `max_hours_between_heating`, `min_spacing_hours`, `force_on_slots`, `heated_today_kwh`.

#### Scenario: Adapter builds per-device config from array
- **WHEN** two enabled water heaters are configured in `water_heaters[]`
- **THEN** the adapter SHALL create two `WaterHeaterInput` objects with each heater's individual settings
- **AND** the adapter SHALL NOT aggregate power or daily minimums across heaters

#### Scenario: Disabled heaters excluded
- **WHEN** a water heater has `enabled: false`
- **THEN** the adapter SHALL NOT include that heater in the `WaterHeaterInput` list

### Requirement: Per-device gap-comfort penalty with deadband
The Kepler solver SHALL bound the time between water-heating blocks per device using a soft, linear discomfort penalty with a deadband at the configured maximum gap. For each enabled heater `d`, the solver SHALL create non-negative variables `discomfort[d][t]` and `gap_over[d][t]` and enforce, for every slot `t` with `duration = slot_hours[t]` and a large constant `M` (100.0):

- `discomfort[d][0] >= duration - water_heat[d][0] * M`
- `discomfort[d][t] >= discomfort[d][t-1] + duration - water_heat[d][t] * M` for `t > 0`
- `gap_over[d][t] >= discomfort[d][t] - deadband`, where `deadband = water_heating_max_gap_hours`

The objective SHALL include `sum over d,t of gap_over[d][t] * water_gap_penalty_sek`. The penalty SHALL be active only when `water_heating_max_gap_hours > 0` AND `water_gap_penalty_sek > 0`; otherwise no gap variables, constraints, or objective term SHALL be added. The formulation SHALL be O(T) per heater (no sliding-window constraints).

#### Scenario: Gaps within the ceiling are free
- **GIVEN** a heater with `max_hours_between_heating = 8` and a schedule where the longest gap between heating is 6 hours
- **WHEN** the solver optimizes
- **THEN** no `gap_over` overshoot is incurred and the gap penalty contributes 0 to the objective

#### Scenario: Gaps beyond the ceiling are penalized and broken up
- **GIVEN** a heater with `max_hours_between_heating = 8`, `water_gap_penalty_sek > 0`, prices cheap overnight and expensive by day
- **WHEN** the solver would otherwise bunch all heating overnight and leave a >8 h daytime gap
- **THEN** the solver SHALL insert a top-up heating block so no gap exceeds ~8 hours, unless the price saving outweighs the accrued gap penalty

#### Scenario: Gap penalty disabled in bulk mode and vacation
- **GIVEN** `enable_top_ups: false` (bulk mode) or vacation mode active, which set `water_heating_max_gap_hours` to 0
- **WHEN** the solver optimizes
- **THEN** no gap-comfort variables, constraints, or objective term SHALL be added

#### Scenario: Counter starts at zero at the horizon start
- **GIVEN** any planning horizon
- **WHEN** the solver builds the discomfort constraints
- **THEN** `discomfort[d][0]` SHALL start from 0 (plus the first slot's duration, less any heating in that slot)

### Requirement: comfort_level scales the gap penalty weight, not the ceiling
The water-heating gap penalty weight `water_gap_penalty_sek` SHALL be derived solely from `comfort_level` via `COMFORT_MAP`, and SHALL increase monotonically from level 1 to level 5. `comfort_level` SHALL NOT modify `max_hours_between_heating` / `water_heating_max_gap_hours`; the gap ceiling SHALL remain exactly the operator-configured value regardless of comfort level.

#### Scenario: Higher comfort level defends the ceiling harder
- **GIVEN** two identical inputs differing only by `comfort_level` (3 vs 5) and `max_hours_between_heating = 8`
- **WHEN** the solver optimizes each
- **THEN** the level-5 plan SHALL incur no smaller a gap penalty per hour of overshoot than the level-3 plan (a larger `water_gap_penalty_sek`), so it tolerates over-ceiling gaps less readily

#### Scenario: Comfort level does not change the ceiling
- **GIVEN** `max_hours_between_heating = 8` at any `comfort_level`
- **WHEN** the solver derives the deadband
- **THEN** the deadband SHALL equal 8 hours for every comfort level

### Requirement: Water comfort control surface is truthful
The configuration and settings UI SHALL expose only water-comfort controls that the solver actually reads: `comfort_level`, per-heater `max_hours_between_heating`, `min_kwh_per_day`, `water_min_spacing_hours`, and `power_kw`. The global `water_heating.reliability_penalty_sek`, `water_heating.block_start_penalty_sek`, `water_heating.spacing_penalty_sek`, and `water_heating.block_penalty_sek` keys SHALL NOT appear in `config.default.yaml` or the settings UI, because the solver derives those weights from `comfort_level` and never reads the keys.

#### Scenario: Dead penalty keys absent from defaults and UI
- **WHEN** inspecting `config.default.yaml` and the settings UI field definitions
- **THEN** none of the four removed `water_heating.*` penalty keys SHALL be present

#### Scenario: Existing config with dead keys still loads
- **GIVEN** a user `config.yaml` that still contains the removed keys
- **WHEN** the app loads the config
- **THEN** the app SHALL load successfully and ignore the extra keys (no error, no behavior change)
