## ADDED Requirements

### Requirement: Price backfill completes unpriced slots without overwriting priced ones
The price backfill SHALL fill both import and export price of recent slots lacking an import price, from the Nordpool price for that exact slot. It SHALL store the raw Nordpool spot export price (no fees or VAT), write only the slots it patched, and never change prices a slot already has. Priced slots in the window SHALL NOT make the backfill fail, and a repeat run SHALL change nothing.

#### Scenario: Gap slots next to normal slots are priced
- **WHEN** the recent window holds slots with stored prices and gap slots with no prices, and Nordpool has prices for the gap slots
- **THEN** each gap slot SHALL be stored with its import price and its raw spot export price
- **AND** the backfill SHALL complete without error

#### Scenario: Existing prices are preserved
- **WHEN** a slot already has import and export prices and the backfill runs
- **THEN** that slot's prices SHALL be unchanged

#### Scenario: Slot with no Nordpool price stays unpriced
- **WHEN** a gap slot has no matching Nordpool price
- **THEN** that slot SHALL remain unpriced and the other gap slots SHALL still be filled

#### Scenario: Repeated backfill is idempotent
- **WHEN** the backfill runs a second time after filling all gap slots
- **THEN** it SHALL report no missing prices and SHALL NOT write any slot
