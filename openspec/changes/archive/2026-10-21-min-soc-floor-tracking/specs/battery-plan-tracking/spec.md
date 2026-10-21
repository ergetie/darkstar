# Spec Delta: battery-plan-tracking

## MODIFIED Requirements

### Requirement: Hold slots use a 2-point margin
In a hold slot the executor SHALL use self-consumption while the rounded live SoC is above the hold floor, SHALL block battery discharge once SoC is at or below it, and SHALL lift the block only when SoC is at or above the target and above the floor. The hold floor is `max(target − 2, min(target, battery.min_soc_percent))`. This applies to every inverter profile. The state SHALL reset when the hold block ends. EV source isolation SHALL keep precedence.

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
- **THEN** the executor SHALL use self-consumption

#### Scenario: Hold below the minimum during recovery
- **GIVEN** `battery.min_soc_percent` is 12 and a hold slot with target 11%
- **WHEN** the live SoC reads 11%
- **THEN** the executor SHALL block battery discharge and SHALL NOT grid charge
- **AND** the block SHALL lift only once the live SoC reaches 12%

#### Scenario: Profiles that write a SoC target are unchanged above the minimum
- **GIVEN** inverter profile `deye`, `battery.min_soc_percent` 12 and a hold slot with target 50%
- **WHEN** the live SoC reads 49%, then 48%
- **THEN** the executor SHALL select self-consumption, then block discharge, writing `soc_target` 50 in both modes as before
