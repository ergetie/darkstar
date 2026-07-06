## ADDED Requirements

### Requirement: Prefer curtailment over loss-making export
The Kepler solver SHALL NOT export surplus PV when doing so costs money. When the effective export price for a slot (`export_price_sek_kwh - export_threshold_sek_per_kwh`) is at or below 0, the solver SHALL prefer curtailing the surplus over exporting it — i.e. the modelled cost of curtailing SHALL NOT exceed the modelled cost of exporting in that slot. When the effective export price is above 0, the existing curtailment penalty (`curtailment_penalty_sek`) SHALL still apply so genuine revenue-positive export is preferred over waste.

#### Scenario: Non-positive export price curtails instead of exporting
- **GIVEN** a slot with surplus PV and an effective export price of 0 (or negative)
- **WHEN** the solver optimizes the slot
- **THEN** the surplus SHALL be curtailed rather than exported
- **AND** the plan SHALL NOT pay the grid to accept the surplus

#### Scenario: Positive export price still exports rather than wastes
- **GIVEN** a slot with surplus PV and a positive effective export price
- **WHEN** the solver optimizes the slot
- **THEN** the surplus SHALL be exported (revenue-positive), not curtailed
