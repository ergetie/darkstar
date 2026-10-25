## MODIFIED Requirements

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
- **WHEN** a slot plans battery charging from PV only, SoC is above the target and EV source isolation is not active
- **THEN** the executor SHALL keep self-consumption mode

### Requirement: EV source isolation always blocks battery discharge
While EV source isolation is active, the controller SHALL select `idle` (unless a grid-charge or export branch applies) for every trigger and at any SoC relative to `soc_target`, including isolated slots with no planned EV kW or keep-on and slots planning PV-only charging (the reason SHALL state that EV charging blocks battery discharge). Isolation keeps precedence over the hold margin; inverter profile idle actions are unchanged.

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
