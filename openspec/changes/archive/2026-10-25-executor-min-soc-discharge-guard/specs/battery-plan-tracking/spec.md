# Spec Delta: battery-plan-tracking

## MODIFIED Requirements

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

## ADDED Requirements

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
