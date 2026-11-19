# Cost Card Import Price Averages

## Purpose

Show the consumption-weighted average import prices for the selected period in the Cost card.

## Requirements

### Requirement: Cost card shows weighted average import prices
The Cost card in the Cost/Energy view SHALL show, for the selected period, the average spot price of imported energy and the average all-in import price, taken from `avg_import_spot_sek_kwh` and `avg_import_price_sek_kwh` of `/api/energy/range`, formatted per kWh with two decimals and the card's currency unit. The rows SHALL appear in the Financial Breakdown directly below Grid Import, SHALL NOT be added to Net, and SHALL use design-system tokens only.

#### Scenario: Both averages displayed
- **WHEN** the range response has `avg_import_spot_sek_kwh` 0.4321 and `avg_import_price_sek_kwh` 1.2345
- **THEN** the card shows "Avg spot price (imported)" as 0.43 SEK/kWh and "Avg import price (all-in)" as 1.23 SEK/kWh

#### Scenario: Null shows empty state
- **WHEN** a value is `null` or absent
- **THEN** its row stays visible and shows a dash instead of a number
- **AND** no `NaN`, `0.00` or `null` text is rendered

#### Scenario: Explanatory tooltips
- **WHEN** the user hovers a row label
- **THEN** the tooltip states the spot row has no fees, tax or VAT, and the all-in row includes grid fees, tax and VAT but not fixed fees

#### Scenario: Period change
- **WHEN** the selected period changes
- **THEN** the rows show the values for the new period
