## ADDED Requirements

### Requirement: Net-excess sink cap accounts for concurrent battery charging
In slots flagged as excess-PV, the solver's cap on total sink consumption (EV surplus, water, and other priority-list sinks) SHALL be `max(0, pv − household_load − battery_charge)` for that slot — concurrent planned battery charging reduces the surplus available to sinks. Sinks SHALL NOT be able to draw grid power while collecting the surplus reward.

#### Scenario: Battery charging consumes the surplus
- **WHEN** a flagged slot has PV 10 kW, load 2 kW, and the solver plans 8 kW of battery charging
- **THEN** total sink consumption in that slot SHALL be capped at 0 kW (not 8 kW)

#### Scenario: Partial battery charge leaves partial surplus
- **WHEN** a flagged slot has PV 10 kW, load 2 kW, and 3 kW battery charging
- **THEN** sinks SHALL be capped at 5 kW

### Requirement: Surplus EV energy counts toward the daily quota
Energy delivered to a charger via `ev_surplus_kw` SHALL count toward that charger's per-day quota cap, so a surplus-rich day does not overshoot the multi-day plan; scheduled plus surplus energy for a day SHALL together respect the day's quota.

#### Scenario: Surplus day respects the quota
- **WHEN** a charger has a 12 kWh quota today and the solver plans 10 kWh scheduled charging
- **THEN** planned surplus charging for today SHALL NOT exceed 2 kWh for that charger

### Requirement: The net-excess constraint has direct regression tests
The net-excess sink cap SHALL be covered by solver-level tests that assert energy magnitudes (sink energy ≤ pv − load − battery charge in flagged slots), not only rank ordering of sinks.

#### Scenario: Regression test exists
- **WHEN** the test suite runs
- **THEN** at least one test SHALL construct a scenario where grid power could masquerade as surplus and assert the solver refuses it by magnitude
