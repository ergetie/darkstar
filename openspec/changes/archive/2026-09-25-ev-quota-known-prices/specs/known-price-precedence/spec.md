## ADDED Requirements

### Requirement: Published spot prices take precedence over forecasts
The system SHALL provide a single per-slot spot price resolver. For every slot with a published Nordpool spot price, that price SHALL be used. The ML forecast (`price_forecasts.spot_p50`, latest `issue_timestamp` per slot) SHALL be used only for slots without a published price.

#### Scenario: Known price overrides a stale forecast
- **WHEN** a slot has a published Nordpool spot of 2.07 SEK/kWh and a forecast `spot_p50` of 0.24 SEK/kWh
- **THEN** the resolved price for that slot SHALL be 2.07 SEK/kWh

#### Scenario: Forecast fills slots beyond the published horizon
- **WHEN** a slot has no published Nordpool price but has a forecast `spot_p50` of 0.6 SEK/kWh
- **THEN** the resolved price for that slot SHALL be 0.6 SEK/kWh

### Requirement: Forecast fallback entries are not treated as known prices
Entries that `get_nordpool_data` synthesizes from the D+1 price forecast fallback SHALL be marked `price_source: "forecast"`. Genuine Nordpool entries SHALL be marked `price_source: "nordpool"`. Only `"nordpool"` entries SHALL count as known prices.

#### Scenario: Pre-auction D+1 fallback
- **WHEN** the time is before 13:00 and D+1 entries come from the forecast fallback
- **THEN** those entries SHALL carry `price_source: "forecast"` and SHALL NOT be returned as known prices

### Requirement: Nordpool unavailability degrades to forecast-only
If published prices cannot be fetched, consumers SHALL fall back to forecast-only prices and SHALL log a warning.

#### Scenario: Nordpool fetch fails
- **WHEN** the Nordpool fetch raises or times out
- **THEN** the per-day averages SHALL be computed from forecasts alone and a warning SHALL be logged
