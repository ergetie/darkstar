## ADDED Requirements

### Requirement: Daily outlook uses published prices where known
For each day in the outlook, slots with a published Nordpool spot price SHALL use that price in place of the forecast when computing `avg_spot_p50`, `min_hour_p50`, and `max_hour_p50`. For those slots, the p10 and p90 contributions SHALL equal the published price. Slots without a published price SHALL keep using the latest forecast run. Response fields and level/confidence classifications SHALL remain unchanged.

#### Scenario: D+1 after the day-ahead auction
- **WHEN** D+1 Nordpool prices are published, averaging ≈2.0 SEK/kWh, while the forecast for D+1 averages 1.2 SEK/kWh
- **THEN** the D+1 entry's `avg_spot_p50` SHALL reflect the published ≈2.0 SEK/kWh

#### Scenario: Days beyond the published horizon
- **WHEN** a day has no published prices
- **THEN** its summary SHALL be computed from the latest forecast run exactly as before
