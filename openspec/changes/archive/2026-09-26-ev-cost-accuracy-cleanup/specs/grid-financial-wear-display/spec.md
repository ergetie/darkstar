## ADDED Requirements

### Requirement: Grid & Financial card shows an EV sub-row under Grid Import
When an EV charger is configured (`system.has_ev_charger`), the card's breakdown section SHALL always include an indented "↳ of which EV" sub-row directly under "Grid Import", even when the period has no EV energy. It SHALL show `ev_cost_sek` (the EV's grid import cost only) as a cost, the total EV kWh, and the solar share as a percentage. When no EV charger is configured, the sub-row SHALL be hidden unless the period has recorded EV energy.

The sub-row SHALL explain, on hover, that the figure is the grid import cost of EV charging, part of Grid Import and not added to Net, and that solar energy is not given a price. The solar share SHALL explain, on hover, that it is the share of EV energy that came from solar and is for information only.

The sub-row SHALL be presented as a component of Grid Import: the headline Net and the other rows SHALL NOT change. It SHALL use design-system tokens.

#### Scenario: EV row with solar share
- **WHEN** the period returns `ev_cost_sek=18.4`, `ev_charging_kwh=12.0`, `ev_solar_share=0.4`
- **THEN** the breakdown SHALL show a "↳ of which EV" sub-row under Grid Import with −18.4 kr, 12.0 kWh and "40% solar"

#### Scenario: Charger configured, no EV energy
- **GIVEN** an EV charger is configured
- **WHEN** `ev_charging_kwh` is 0 for the period
- **THEN** the EV sub-row SHALL show "0 kr" and "0 kWh" without a solar share

#### Scenario: No charger configured
- **GIVEN** no EV charger is configured
- **WHEN** `ev_charging_kwh` is 0 for the period
- **THEN** the EV sub-row SHALL be hidden

#### Scenario: Solar share explained
- **WHEN** the row shows a solar share
- **THEN** hovering it SHALL explain that it is the share of EV energy from solar, for information only

#### Scenario: Headline unchanged
- **WHEN** EV cost is non-zero
- **THEN** the headline Net SHALL still equal `net_cost_sek`
