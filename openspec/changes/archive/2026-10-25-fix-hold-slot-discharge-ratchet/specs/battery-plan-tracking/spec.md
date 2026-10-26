## ADDED Requirements

### Requirement: Hold slots block battery discharge
In a hold slot (planned `discharge_kw` 0, no EV isolation, no charge, export or discharge-at-floor branch) the executor SHALL select `idle` at every live SoC and `soc_target`, with a reason naming the hold. The decision SHALL NOT depend on PV forecast, measured PV or target changes between plans. PV charging SHALL remain possible and the charge limit SHALL NOT be capped. Hold slots SHALL carry no state and SHALL reset a preceding charge latch. EV isolation keeps precedence.

#### Scenario: Hold slot idles at any SoC
- **GIVEN** a hold slot with target 50%
- **WHEN** the live SoC reads 60%, 50%, 49% or 40%
- **THEN** the executor SHALL select idle and the reason SHALL name the hold

#### Scenario: Mode is stable across a hold block
- **GIVEN** a hold slot with target 50%
- **WHEN** the live SoC alternates between 49% and 50% on successive ticks
- **THEN** the executor SHALL select idle on every tick and SHALL NOT select self-consumption

#### Scenario: Replans with falling targets do not ratchet
- **GIVEN** successive plans whose hold slot targets fall as the entry SoC is re-seeded (96, 94, 92, 90)
- **WHEN** the live SoC equals each new target in turn
- **THEN** the executor SHALL select idle every time and SHALL NOT select self-consumption at any of them

#### Scenario: Idle in a hold slot still allows PV charging
- **GIVEN** any inverter profile (`fronius`, `deye`, `sungrow`, `generic`)
- **WHEN** the executor selects idle for a hold slot
- **THEN** the profile's idle actions SHALL NOT write a zero charge limit, so PV can still charge the battery

#### Scenario: Hold at the minimum
- **GIVEN** `battery.min_soc_percent` is 12 and a hold slot with target 12% (or 11% during recovery)
- **WHEN** the live SoC reads 11%, 12%, 13% or 14%
- **THEN** the executor SHALL select idle and SHALL NOT grid charge

#### Scenario: EV isolation keeps precedence
- **GIVEN** a hold slot with EV source isolation active
- **THEN** the decision SHALL be idle with the isolation reason, not the hold reason

#### Scenario: Previous charge latch is reset
- **GIVEN** a grid-charge block stopped at its target (latch engaged)
- **WHEN** a hold slot starts and a later grid-charge block begins with live SoC 2 points below its target
- **THEN** the later block SHALL charge, as for any new block

#### Scenario: Minimum-SoC guard outlasts the hold
- **GIVEN** the live SoC is at or near `battery.min_soc_percent`
- **WHEN** a hold block ends and a slot follows that plans self-consumption
- **THEN** the minimum-SoC discharge guard SHALL keep discharge blocked until the live SoC reaches `min_soc_percent + 2`

## MODIFIED Requirements

### Requirement: EV source isolation always blocks battery discharge
While EV source isolation is active, the controller SHALL select `idle` (unless a grid-charge or export branch applies) for every trigger and at any SoC relative to `soc_target`, including isolated slots with no planned EV kW or keep-on and slots planning PV-only charging (the reason SHALL state that EV charging blocks battery discharge). Isolation keeps precedence over hold-slot handling; inverter profile idle actions are unchanged.

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

#### Scenario: Planned PV charge with isolation by the engine
- **GIVEN** a slot with `charge_kw` > 0, no grid charging and `discharge_blocked_by_ev` set
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`, not `self_consumption`
- **AND** the decision reason SHALL state that EV charging blocks battery discharge

#### Scenario: Planned PV charge with planned EV charging
- **GIVEN** a slot with `charge_kw` > 0, no grid charging, and `ev_charging_kw` above 0.1
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Planned PV charge with keep-on only
- **GIVEN** a slot with `charge_kw` > 0, no grid charging, no planned EV kW and a keep-on flag set
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle`

#### Scenario: Planned PV charge without EV charging is unchanged
- **GIVEN** a slot with `charge_kw` > 0, no grid charging, and no isolation trigger
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `self_consumption`

#### Scenario: Planned grid charge is not overridden
- **GIVEN** isolation is active and the slot plans grid charging below its target
- **WHEN** the executor evaluates the slot
- **THEN** the charge branch SHALL still apply

#### Scenario: Composes with the minimum-SoC discharge guard
- **GIVEN** isolation is active and the min-SoC guard latch is engaged
- **WHEN** the executor evaluates the slot
- **THEN** the decision mode SHALL be `idle` and the isolation reason SHALL be kept; the guard SHALL NOT alter an already-idle isolated slot, and its latch SHALL keep updating from live SoC

## REMOVED Requirements

### Requirement: Hold slots use a 2-point margin
**Reason**: The margin let SoC ratchet down: each 30-minute replan lowers the hold target to the new entry SoC and clears the hold latch, re-arming a fresh 2-point margin (observed 96% to 89% with zero planned discharge, 12 mode changes per hour). The planner models a hold as zero discharge, so the margin contradicted the plan.
**Migration**: Replaced by "Hold slots block battery discharge". Hold slots select idle at every SoC; the hold floor, latch, lift rule and `min_soc_percent` bound of the hold margin no longer exist. The charge-target resume margin and the minimum-SoC guard margin (2 points) are unchanged.
