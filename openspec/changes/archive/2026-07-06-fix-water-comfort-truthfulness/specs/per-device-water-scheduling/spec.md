## ADDED Requirements

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
