## ADDED Requirements

### Requirement: Range endpoint returns consumption-weighted average import prices
`GET /api/energy/range` SHALL return `avg_import_spot_sek_kwh` and `avg_import_price_sek_kwh`, the imported-kWh-weighted averages of `export_price_sek_kwh` (pure Nordpool spot, no fees, tax or VAT) and `import_price_sek_kwh` (all-in) over slots with `import_kwh > 0` and a non-NULL respective price. Fixed fees SHALL NOT be included. Each value SHALL be `null` when no slot qualifies. Existing fields SHALL be unchanged.

#### Scenario: Weighted by imported kWh
- **WHEN** slot A imports 1 kWh at spot 1.00 and slot B imports 3 kWh at spot 2.00
- **THEN** `avg_import_spot_sek_kwh` is 1.75, not the simple mean 1.50

#### Scenario: All-in average uses import price
- **WHEN** slot A imports 1 kWh at all-in price 2.00 and slot B imports 3 kWh at all-in price 4.00
- **THEN** `avg_import_price_sek_kwh` is 3.5

#### Scenario: NULL price excluded from numerator and denominator
- **WHEN** a slot imports 5 kWh with a NULL `export_price_sek_kwh` and another imports 1 kWh at spot 1.00
- **THEN** `avg_import_spot_sek_kwh` is 1.0
- **AND** the NULL-priced slot is not treated as price 0

#### Scenario: Prices are excluded independently
- **WHEN** a slot has a spot price but a NULL `import_price_sek_kwh`
- **THEN** it counts toward `avg_import_spot_sek_kwh` only

#### Scenario: Zero price is a real value
- **WHEN** a slot imports 2 kWh at spot price 0.0
- **THEN** it is included in the average with price 0

#### Scenario: Slots without import ignored
- **WHEN** a slot has `import_kwh` of 0 or NULL
- **THEN** it does not affect either average, whatever its prices

#### Scenario: No qualifying import yields null
- **WHEN** the period has no slots, no slot with `import_kwh > 0`, or no such slot has a price
- **THEN** the corresponding average is `null`

#### Scenario: Fixed fees not included
- **WHEN** fixed fees are configured and `fixed_fees_sek` is greater than 0
- **THEN** both averages equal the values computed without fixed fees

#### Scenario: Zero-fallback response
- **WHEN** the endpoint returns its exception fallback response
- **THEN** both fields are present with value `null`
