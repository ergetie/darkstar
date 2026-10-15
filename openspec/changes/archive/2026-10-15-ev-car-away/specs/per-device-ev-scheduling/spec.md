## MODIFIED Requirements

### Requirement: Per-device discharge blocking
The solver SHALL enforce discharge blocking when ANY plugged-in charger is charging: `discharge[t] <= (1 - any_ev_charging[t]) * M` where `any_ev_charging[t]` is 1 if any plugged-in charger is active in slot t. Planned charging for an assumed-plugged charger (unplugged, with an active goal) SHALL NOT set `any_ev_charging[t]` and SHALL NOT block battery discharge. Its planned EV energy SHALL still be limited to grid import plus PV in that slot.

#### Scenario: One charger active blocks discharge
- **WHEN** plugged-in charger A is charging in slot t and charger B is not
- **THEN** battery discharge SHALL be zero in slot t

#### Scenario: No chargers active allows normal discharge
- **WHEN** no charger is charging in slot t
- **THEN** battery discharge SHALL be bounded only by its normal upper bound

#### Scenario: Assumed-plugged charging does not block discharge
- **WHEN** an unplugged charger with an active goal is planned to charge in slot t and no plugged-in charger is charging in slot t
- **THEN** battery discharge in slot t SHALL be bounded only by its normal upper bound
- **AND** the planned EV energy in slot t SHALL NOT exceed grid import plus PV in slot t
- **AND** the house battery plan SHALL equal the plan for the same inputs without that charger's planned charging, apart from the extra grid import for the EV

#### Scenario: Car plugged in restores the block
- **WHEN** the same charger is plugged in and the planner replans
- **THEN** battery discharge SHALL be zero in every slot where that charger is planned to charge
