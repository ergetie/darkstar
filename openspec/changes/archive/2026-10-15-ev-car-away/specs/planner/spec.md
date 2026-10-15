## MODIFIED Requirements

### Requirement: Solver blocks battery discharge during EV charging
The solver SHALL force battery discharge to zero in any slot where ANY plugged-in EV charger is charging. This SHALL be enforced by introducing an auxiliary binary `any_ev_charging[t]` that is 1 when any plugged-in charger's `ev_charge[d][t]` is 1, then applying the Big-M constraint: `discharge[t] <= (1 - any_ev_charging[t]) * M`, where `M = max_discharge_kw * slot_hours[t]`. The linking constraints SHALL be: `any_ev_charging[t] >= ev_charge[d][t]` for each plugged-in device d, and `any_ev_charging[t] <= sum(ev_charge[d][t] for plugged-in d)`. Assumed-plugged chargers SHALL be excluded from these linking constraints. This constraint SHALL only be added when at least one plugged-in EV charger is present in the solver input.

#### Scenario: One of two chargers active forces zero discharge
- **WHEN** the solver schedules plugged-in charger A to charge in slot t (`ev_charge[A][t] = 1`) and charger B is idle (`ev_charge[B][t] = 0`)
- **THEN** `any_ev_charging[t]` is forced to 1
- **AND** `discharge[t]` is forced to 0.0 by the Big-M constraint

#### Scenario: No chargers active allows normal discharge
- **WHEN** no charger is scheduled in slot t (all `ev_charge[d][t] = 0`)
- **THEN** `any_ev_charging[t]` is 0
- **AND** `discharge[t]` is bounded only by its normal upper bound

#### Scenario: EV disabled users are unaffected
- **WHEN** no EV chargers are present in the solver input
- **THEN** no EV-related discharge constraint is added to the MILP model
- **AND** solver behavior is identical to before this change

#### Scenario: Only assumed-plugged chargers present
- **WHEN** the only EV charger in the solver input is assumed plugged
- **THEN** no EV-related discharge constraint SHALL be added to the MILP model
