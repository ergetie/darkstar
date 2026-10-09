## MODIFIED Requirements

### Requirement: Per-device daily minimum energy constraint
The solver SHALL enforce a per-device daily minimum energy constraint for each heater: `sum(water_heat[d][t] * power_kw * h for t in day_slots) >= min_kwh_per_day - heated_today_kwh - violation[d]`. The violation variable is penalized by the global `water_reliability_penalty_sek`. `heated_today_kwh` SHALL be credited only to the first already-started quota bucket. A shared local-time bucket definition SHALL govern solver grouping and measured progress: with deferral h, bucket D covers `[D at h:00, D+1 at h:00)`. Each energy interval SHALL belong to exactly one bucket; timezone/DST transitions SHALL use actual elapsed durations. Minimums SHALL remain soft minimums, not upper limits on heating.

#### Scenario: Two heaters with different daily requirements
- **WHEN** heater A has `min_kwh_per_day: 6.0` and heater B has `min_kwh_per_day: 4.0`
- **THEN** the solver SHALL enforce 6.0 kWh minimum for heater A and 4.0 kWh minimum for heater B independently

#### Scenario: Heater with today's progress deducted
- **WHEN** heater A has `min_kwh_per_day: 6.0` and has already heated 3.0 kWh today
- **THEN** the solver SHALL require at least 3.0 kWh more for heater A

#### Scenario: Smart deferral applies per-device
- **WHEN** `defer_up_to_hours: 6` is configured globally
- **THEN** each heater's daily minimum constraint SHALL extend into the early morning hours of the next day independently

#### Scenario: Shifted quota boundary
- **WHEN** deferral is 6 hours and planning occurs at 02:00 local time
- **THEN** the active quota bucket SHALL run from 06:00 the previous day to 06:00 that day
- **AND** measured progress and planned slots SHALL use that same bucket

#### Scenario: Fractional boundary and DST
- **WHEN** a supported fractional deferral boundary or daylight-saving transition occurs inside the measured window
- **THEN** energy SHALL be apportioned by the actual boundary and elapsed time without omission or double credit
- **AND** all later buckets SHALL keep their independent daily minimum

### Requirement: Per-device gap-comfort penalty with deadband
The Kepler solver SHALL bound the time between water-heating blocks per device using a soft, linear discomfort penalty with a deadband at the configured maximum gap. For each enabled heater `d`, the solver SHALL create non-negative variables `discomfort[d][t]` and `gap_over[d][t]` and enforce, for every slot `t` with `duration = slot_hours[t]` and a large constant `M` (100.0):

- `discomfort[d][0] >= duration - water_heat[d][0] * M`
- `discomfort[d][t] >= discomfort[d][t-1] + duration - water_heat[d][t] * M` for `t > 0`
- `gap_over[d][t] >= discomfort[d][t] - deadband`, where `deadband = heater.max_hours_between_heating` for device `d`

The objective SHALL include `sum over d,t of gap_over[d][t] * water_gap_penalty_sek`. The penalty SHALL be active for each heater only when its `max_hours_between_heating > 0`, top-ups are enabled, vacation mode is inactive, AND `water_gap_penalty_sek > 0`; otherwise no gap variables, constraints, or objective term SHALL be added. The formulation SHALL be O(T) per heater (no sliding-window constraints).

#### Scenario: Gaps within the ceiling are free
- **GIVEN** a heater with `max_hours_between_heating = 8` and a schedule where the longest gap between heating is 6 hours
- **WHEN** the solver optimizes
- **THEN** no `gap_over` overshoot is incurred and the gap penalty contributes 0 to the objective

#### Scenario: Gaps beyond the ceiling are penalized and broken up
- **GIVEN** a heater with `max_hours_between_heating = 8`, `water_gap_penalty_sek > 0`, prices cheap overnight and expensive by day
- **WHEN** the solver would otherwise bunch all heating overnight and leave a >8 h daytime gap
- **THEN** the solver SHALL insert a top-up heating block so no gap exceeds ~8 hours, unless the price saving outweighs the accrued gap penalty

#### Scenario: Gap penalty disabled in bulk mode and vacation
- **GIVEN** `enable_top_ups: false` (bulk mode) or vacation mode active, which disable gap comfort globally
- **WHEN** the solver optimizes
- **THEN** no gap-comfort variables, constraints, or objective term SHALL be added

#### Scenario: Counter starts at zero at the horizon start
- **GIVEN** any planning horizon
- **WHEN** the solver builds the discomfort constraints
- **THEN** `discomfort[d][0]` SHALL start from 0 (plus the first slot's duration, less any heating in that slot)

#### Scenario: Different heater gaps are honored
- **WHEN** heater A has maximum gap 28 hours and heater B has maximum gap 8 hours
- **THEN** each SHALL use its own deadband rather than a shared default of 8 hours
- **AND** their gap penalties SHALL activate independently

### Requirement: comfort_level scales the gap penalty weight, not the ceiling
The water-heating gap penalty weight `water_gap_penalty_sek` SHALL be derived solely from `comfort_level` via `COMFORT_MAP`, and SHALL increase monotonically from level 1 to level 5. `comfort_level` SHALL NOT modify each heater's `max_hours_between_heating`; the gap ceiling SHALL remain exactly the operator-configured value regardless of comfort level.

#### Scenario: Higher comfort level defends the ceiling harder
- **GIVEN** two identical inputs differing only by `comfort_level` (3 vs 5) and `max_hours_between_heating = 8`
- **WHEN** the solver optimizes each
- **THEN** the level-5 plan SHALL incur no smaller a gap penalty per hour of overshoot than the level-3 plan (a larger `water_gap_penalty_sek`), so it tolerates over-ceiling gaps less readily

#### Scenario: Comfort level does not change the ceiling
- **GIVEN** `max_hours_between_heating = 8` at any `comfort_level`
- **WHEN** the solver derives the deadband
- **THEN** the deadband SHALL equal 8 hours for every comfort level

## ADDED Requirements

### Requirement: Water settings validate effective scheduling inputs
Configuration load and settings save SHALL reject non-finite deferral and values outside 0–23 hours inclusive with a field-specific actionable error. Settings SHALL expose the same bounds and explain the local-time quota boundary. The system SHALL NOT silently clamp or reinterpret invalid existing values. Per-heater maximum-gap settings SHALL support values above 24 hours, including 28, consistently with solver inputs. Per-heater `idle_power_threshold_kw` SHALL be configurable with explicit units and non-negative finite validation, default 0, and guidance explaining active-energy filtering.

#### Scenario: Existing out-of-range deferral
- **WHEN** a configuration sets `water_heating.defer_up_to_hours` to 30
- **THEN** validation SHALL name that field, state the supported 0–23 range and require explicit correction
- **AND** the value SHALL NOT be interpreted as a one-day shift or silently clamped

#### Scenario: Settings update remains atomic
- **WHEN** an operator attempts to save an invalid deferral or idle cutoff
- **THEN** the save SHALL fail with a field-specific error and leave the last valid configuration intact

#### Scenario: Supported bounds and long gaps
- **WHEN** deferral is 0 or 23, a heater's maximum gap is 28 hours and its idle cutoff is 0.10 kW
- **THEN** backend validation and settings UI SHALL accept those values and pass their effective values through to the responsible processing paths
- **AND** changing comfort level SHALL NOT alter the 28-hour deadband

#### Scenario: Existing cutoff omitted
- **WHEN** a valid older configuration omits the idle cutoff
- **THEN** the cutoff SHALL default to 0 and preserve previous sample inclusion
- **AND** the settings help SHALL explain when an operator can configure a cutoff such as 0.10 kW for a roughly 0.06 kW idle draw
