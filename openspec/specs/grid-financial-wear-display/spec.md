# Grid Financial Wear Display

## Purpose

UI display of battery wear cost in the Grid & Financial summary card, showing the true total cost of energy including battery degradation.

## Requirements

### Requirement: Grid & Financial card shows net including battery wear
The Grid & Financial card SHALL display a secondary line beneath the headline Net figure showing the net cost including battery wear, sourced from the endpoint's `net_cost_incl_wear_sek`. This secondary line SHALL be visually distinct (it "pops out") from the surrounding breakdown text so the user can read it at a glance. The headline Net figure SHALL continue to show `net_cost_sek` (real grid cash flow) and SHALL NOT change.

The secondary line SHALL follow the same sign and color convention as the headline (savings vs. cost), applied to the wear-inclusive value.

#### Scenario: Secondary net-incl-wear line is shown
- **WHEN** the card renders with period data available
- **THEN** the headline shows the pure-grid Net (`net_cost_sek`)
- **AND** a distinct secondary line below shows the net including battery wear (`net_cost_incl_wear_sek`)

#### Scenario: Headline Net is unchanged by this feature
- **WHEN** battery wear is non-zero for the period
- **THEN** the headline Net value matches `net_cost_sek` exactly (wear is not folded into it)

### Requirement: Grid & Financial card shows a Battery Wear breakdown row
The financial breakdown section of the card SHALL include a "Battery Wear" row showing `battery_wear_cost_sek` for the period, presented as a cost alongside the existing breakdown rows (Grid Import, Export Rev, Battery Charge, Self-Use Saved).

#### Scenario: Battery Wear row appears in the breakdown
- **WHEN** the breakdown section renders for a period with battery throughput
- **THEN** a "Battery Wear" row shows the `battery_wear_cost_sek` value
- **AND** it is presented consistently with the other breakdown rows

#### Scenario: Zero wear renders cleanly
- **WHEN** the period has no battery throughput
- **THEN** the "Battery Wear" row shows `0.00`
