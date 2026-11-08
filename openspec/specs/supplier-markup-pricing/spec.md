# Supplier Markup Pricing

## Purpose

Supplier markup handling in the price formula. (TBD: refine)

## Requirements

### Requirement: Supplier markup in import price
Import price SHALL be (spot + transfer + energy tax + supplier markup) * (1 + VAT), with `pricing.supplier_markup_sek_kwh` excl VAT defaulting to 0. Export price SHALL remain raw spot.

#### Scenario: Markup applied
- **WHEN** spot 0.50, transfer 0.2584, tax 0.36, markup 0.1132, VAT 25%
- **THEN** import is 1.5395 SEK/kWh and export is 0.50

### Requirement: Energy tax default
The default energy tax SHALL be 0.36 SEK/kWh excl VAT in the code fallback, config.default.yaml, onboarding and help text.

#### Scenario: Missing key
- **WHEN** `pricing.energy_tax_sek` is absent
- **THEN** 0.36 is used

### Requirement: Energy tax migration
Config migration SHALL rewrite `energy_tax_sek` to 0.36 only if it equals 0.439.

#### Scenario: Custom value kept
- **WHEN** the value is 0.45
- **THEN** it is unchanged

### Requirement: Shared formula in backfill scripts
Backfill scripts SHALL compute prices via the shared price function, honouring time-of-use transfer rules.

#### Scenario: Time-of-use
- **WHEN** a backfill slot falls in a time-of-use window
- **THEN** its import price uses that window's transfer fee

### Requirement: Settings layout
Settings SHALL group "Grid operator" (monthly subscription fee, transfer fee, energy tax) and "Electricity supplier" (yearly fee, markups, VAT %, recalculate action), all amounts excl VAT, with help text.

#### Scenario: New keys
- **WHEN** an existing config lacks the new keys
- **THEN** they are filled with 0
