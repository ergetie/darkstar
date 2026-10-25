# Spec: Battery Plan Tracking

## Purpose

Keep the house battery consistent with the plan at runtime: grid charging never runs past the planned SoC, hold slots do not flip modes on small SoC changes, and a plan that no longer matches the real battery is replaced promptly.

## Requirements

### Requirement: Grid charging stops at the planned target
In a slot planned for grid charging, the executor SHALL charge only while the rounded live SoC is below the slot's `soc_target`. Once it reaches or exceeds the target, the executor SHALL hold the battery (no grid charging, no discharge) for the remaining slots of that charge block. Solar-only charging slots, manual overrides and Battery Top Up SHALL keep their own behaviour.

#### Scenario: Target reached mid-block
- **GIVEN** a grid-charge block with `soc_target` 18%
- **WHEN** the live SoC reads 18%
- **THEN** the executor SHALL select hold instead of charge

#### Scenario: Already above target at block start
- **WHEN** a grid-charge slot starts with live SoC above its `soc_target`
- **THEN** the executor SHALL NOT grid charge in that slot

#### Scenario: Solar-only charging unaffected
- **WHEN** a slot plans battery charging from PV only and SoC is above the target
- **THEN** the executor SHALL keep self-consumption mode

### Requirement: Stopped grid charging resumes only clearly below target
After grid charging stopped at target within a charge block, the executor SHALL resume grid charging in that block only when the live SoC falls at least 2 percentage points below the target. The latch SHALL reset when the charge block ends.

#### Scenario: Small dip keeps holding
- **GIVEN** grid charging stopped at target 18% in the current block
- **WHEN** the live SoC reads 17%
- **THEN** the executor SHALL keep holding

#### Scenario: Clear drop resumes charging
- **GIVEN** grid charging stopped at target 18% in the current block
- **WHEN** the live SoC reads 15%
- **THEN** the executor SHALL resume grid charging

### Requirement: Hold slots use a 2-point margin
In a hold slot the executor SHALL use self-consumption while the rounded live SoC is above the hold floor `max(target − 2, min(target, battery.min_soc_percent))`, SHALL block battery discharge at or below it, and SHALL lift the block only when SoC is at or above the target and above the floor. EV source isolation keeps precedence.

#### Scenario: Small drop stays on auto
- **GIVEN** a hold slot with target 50%
- **WHEN** the live SoC reads 49%
- **THEN** the executor SHALL use self-consumption

#### Scenario: Margin used up
- **GIVEN** a hold slot with target 50%
- **WHEN** the live SoC reads 48%
- **THEN** the executor SHALL block battery discharge

#### Scenario: No flip on one point of PV
- **GIVEN** discharge was blocked at 48% in a hold slot with target 50%
- **WHEN** PV raises the SoC to 49%
- **THEN** the executor SHALL keep blocking discharge

#### Scenario: Back at target
- **GIVEN** discharge was blocked in a hold slot with target 50%
- **WHEN** the live SoC reads 50%
- **THEN** the executor SHALL use self-consumption

#### Scenario: Margin never crosses the minimum
- **GIVEN** `battery.min_soc_percent` is 12 and a hold slot with target 13%
- **WHEN** the live SoC reads 12%
- **THEN** the executor SHALL block battery discharge

#### Scenario: Hold at the minimum blocks immediately
- **GIVEN** `battery.min_soc_percent` is 12, inverter profile `fronius`, and a hold slot with target 12%
- **WHEN** the live SoC reads 12%
- **THEN** the executor SHALL block battery discharge
- **AND** it SHALL NOT select self-consumption on the following ticks while the SoC stays at 12%

#### Scenario: Hold at the minimum lifts only on a real gain
- **GIVEN** discharge was blocked in a hold slot with target 12% and `battery.min_soc_percent` 12
- **WHEN** PV raises the live SoC to 13%
- **THEN** the executor SHALL keep blocking discharge
- **WHEN** the live SoC then reads 14%
- **THEN** the executor SHALL use self-consumption

#### Scenario: Hold below the minimum during recovery
- **GIVEN** `battery.min_soc_percent` is 12 and a hold slot with target 11%
- **WHEN** the live SoC reads 11%
- **THEN** the executor SHALL block battery discharge and SHALL NOT grid charge
- **AND** discharge SHALL stay blocked at 12% and 13% and SHALL be allowed again only once the live SoC reaches 14%

#### Scenario: Profiles that write a SoC target are unchanged above the minimum
- **GIVEN** inverter profile `deye`, `battery.min_soc_percent` 12 and a hold slot with target 50%
- **WHEN** the live SoC reads 49%, then 48%
- **THEN** the executor SHALL select self-consumption, then block discharge, writing `soc_target` 50 in both modes as before

#### Scenario: Hold state applies to every profile and resets
- **GIVEN** any inverter profile and a hold block
- **THEN** the same floor and lift rules SHALL apply
- **WHEN** the hold block ends
- **THEN** the hold state SHALL reset

#### Scenario: Minimum-SoC guard outlasts the hold block
- **GIVEN** the live SoC is at or near `battery.min_soc_percent`
- **WHEN** the hold block lifts
- **THEN** the minimum-SoC discharge guard SHALL keep discharge blocked until the live SoC reaches `min_soc_percent + 2`

### Requirement: Replan when the battery deviates from the plan
The executor SHALL compare the live SoC with the plan's expected SoC now, interpolated linearly within the slot between its entry SoC and its projected end SoC. When the absolute deviation stays above `executor.soc_deviation_replan_percent` (default 10, 0 disables) for 5 minutes, it SHALL request an immediate planner run with reason `soc_deviation` and log the live SoC, the expected SoC and the threshold.

#### Scenario: Battery far below plan
- **GIVEN** the plan expects 15% now and the threshold is 10
- **WHEN** the live SoC reads 3% continuously for 5 minutes
- **THEN** one replan with reason `soc_deviation` SHALL be requested

#### Scenario: Short deviation
- **WHEN** the deviation exceeds the threshold for 3 minutes and then falls back below it
- **THEN** no replan SHALL be requested

#### Scenario: Disabled
- **WHEN** `executor.soc_deviation_replan_percent` is 0
- **THEN** no `soc_deviation` replan SHALL ever be requested

### Requirement: SoC deviation replans are limited
The executor SHALL request at most one `soc_deviation` replan per 15 minutes, independently of other replan limits. It SHALL NOT request one while the SoC reading is unavailable or while a manual override or Battery Top Up is active. In shadow mode it SHALL only log that it would replan.

#### Scenario: Rate limit
- **GIVEN** a `soc_deviation` replan was requested 5 minutes ago
- **WHEN** the deviation is still above the threshold
- **THEN** no further `soc_deviation` replan SHALL be requested until 15 minutes have passed

#### Scenario: Unavailable SoC
- **WHEN** the battery SoC sensor is unavailable
- **THEN** no `soc_deviation` replan SHALL be requested

### Requirement: Deviation threshold is a user setting
The settings UI SHALL expose `executor.soc_deviation_replan_percent` (0–50, default 10) with help text stating that 0 disables it and that the deviation must last 5 minutes.

#### Scenario: Setting changed
- **WHEN** the user sets the threshold to 15 and saves
- **THEN** the executor SHALL use 15 from its next config reload

### Requirement: Minimum-SoC discharge guard
The executor SHALL keep a min-SoC guard latch, independent of the per-block plan state, on every inverter profile. It SHALL engage when the rounded live SoC is at or below `battery.min_soc_percent` and release at or above `min_soc_percent + 2`. While engaged, plan-following `self_consumption` or `export` SHALL become `idle`, with a reason naming the guard.

#### Scenario: Planned PV charge at the minimum
- **GIVEN** `min_soc_percent` 12, a slot with `charge_kw` > 0 and no grid charge
- **WHEN** the live SoC reads 12%
- **THEN** the executor SHALL select idle, not self-consumption
- **AND** the decision reason SHALL name the min-SoC guard

#### Scenario: Export at the minimum
- **GIVEN** `min_soc_percent` 12 and a slot planning export from the battery
- **WHEN** the live SoC reads 11%
- **THEN** the executor SHALL select idle

#### Scenario: Release needs the margin
- **GIVEN** the latch engaged at 12% with `min_soc_percent` 12
- **WHEN** the live SoC reads 13%
- **THEN** the executor SHALL keep idle
- **WHEN** the live SoC then reads 14%
- **THEN** the executor SHALL follow the plan again

#### Scenario: Latch survives a slot change
- **GIVEN** the latch engaged in one slot
- **WHEN** the next slot starts or the plan is replaced and the SoC is still below 14%
- **THEN** the executor SHALL still replace self-consumption with idle
- **AND** the latch SHALL persist across slot changes and replans

#### Scenario: Unreadable SoC keeps state
- **GIVEN** the latch is engaged (or released) and `soc_available` is False
- **THEN** the latch SHALL neither engage nor release and SHALL keep its previous state

#### Scenario: Charge slots untouched
- **GIVEN** the latch is engaged and a slot plans grid charging (or idle)
- **THEN** the executor SHALL follow the charge (or idle) decision unchanged

#### Scenario: No price logic in the guard
- **GIVEN** the latch is engaged
- **WHEN** grid prices are high or low
- **THEN** the guard SHALL NOT consider prices and SHALL only depend on the live SoC

#### Scenario: Profile with a hardware SoC floor
- **GIVEN** a profile that writes `soc_target` in every mode (such as `deye`)
- **WHEN** the guard replaces self-consumption with idle
- **THEN** the profile's `soc_target` handling SHALL be unchanged

### Requirement: EV source isolation always blocks battery discharge
While EV source isolation is active, the controller SHALL select `idle` (unless a charge or export branch applies) for every trigger and at any SoC relative to `soc_target`, and SHALL recognise the isolated slot even with no planned EV kW and no keep-on. Isolation keeps precedence over the hold margin; inverter profile idle actions are unchanged.

#### Scenario: Manual EV charge above the SoC target
- **GIVEN** an active manual EV charge, a slot with `ev_charging_kw` 0 and no keep-on, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`, not `self_consumption`

#### Scenario: Actual unplanned charging above the SoC target
- **GIVEN** measured EV power above 0.1 kW and no planned EV charging, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Surplus-eligible slot above the SoC target
- **GIVEN** a slot with surplus-eligible EV kW and `ev_charging_kw` 0, and live SoC above `soc_target`
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Planned grid charge is not overridden
- **GIVEN** isolation is active and the slot plans grid charging below its target
- **WHEN** the executor evaluates the slot
- **THEN** the charge branch SHALL still apply

#### Scenario: Composes with the minimum-SoC discharge guard
- **GIVEN** isolation is active and the min-SoC guard latch is engaged
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle` and the isolation reason SHALL be kept; the guard SHALL NOT alter an already-idle isolated slot, and its latch SHALL keep updating from live SoC
