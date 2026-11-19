# Spec: Configured Currency Display

## Purpose
Show every monetary amount in the configured currency, from one source, so other currencies need only configuration.

## Requirements

### Requirement: Single currency source
The UI and user-facing backend messages SHALL derive the currency code from `nordpool.currency`; no literal currency is hardcoded outside the subunit table.

#### Scenario: Configured EUR
- **WHEN** `nordpool.currency` is `EUR`
- **THEN** prices render as "0.12 EUR/kWh" and costs as "3.40 EUR"

#### Scenario: Not yet loaded
- **WHEN** the currency is not yet known
- **THEN** numbers render without a unit

#### Scenario: Empty or invalid backend currency
- **WHEN** `nordpool.currency` is missing, empty or not a three-letter code
- **THEN** user-facing backend messages use the default code SEK

### Requirement: Subunit derived from code
A subunit name and factor SHALL be derived from the currency code (SEK to öre, NOK and DKK to øre, EUR to cent); currencies without an entry SHALL show the main unit.

#### Scenario: SEK subunit
- **WHEN** a price of 1.28 SEK/kWh is shown in subunits
- **THEN** it renders "128 öre/kWh"

### Requirement: Price outlook tooltip is correct
The 7-day price outlook tooltip SHALL show the day average in the configured price unit and label the percentile values "P10" and "P90" and the hour extremes "Lowest hour" and "Highest hour".

#### Scenario: Tooltip
- **WHEN** a day has avg_spot_p50 2.9 and currency SEK
- **THEN** the tooltip shows "2.90 SEK/kWh" and no "öre"
