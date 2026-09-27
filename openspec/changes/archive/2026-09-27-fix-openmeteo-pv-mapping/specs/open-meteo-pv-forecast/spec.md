## ADDED Requirements

### Requirement: Efficient Live PV Slot Mapping

The live Open-Meteo forecast path SHALL map PV power to each requested slot by direct timestamp lookup, so that mapping cost does not grow with the length of the fetched solar series. The mapped values MUST be identical to matching each slot's 15-minute-rounded start time against the series by UTC instant.

#### Scenario: Slot matches a series timestamp in a different timezone
- **WHEN** a slot start is a pytz-aware local timestamp and the series key for the same instant is a fixed-offset aware datetime
- **THEN** the slot SHALL receive that key's summed watts converted to kWh (`watts * 0.25 / 1000`)

#### Scenario: Slot has no matching series timestamp
- **WHEN** no series key equals the slot's rounded start instant
- **THEN** the slot's PV forecast SHALL be 0.0 kWh

#### Scenario: Long series does not slow mapping
- **WHEN** the fetched series contains thousands of historical entries before the first requested slot
- **THEN** mapping a 7-day (672-slot) request SHALL complete in well under one second and produce the same values as with only the relevant entries

### Requirement: Live PV Fetch Requests Minimal History

The live Open-Meteo PV fetch in `_get_forecast_data_async` SHALL request `past_days=1` for every configured solar array instead of relying on the library default.

#### Scenario: Each array requests one past day
- **WHEN** the live forecast is fetched for one or more solar arrays
- **THEN** every `OpenMeteoSolarForecast` instance SHALL be constructed with `past_days=1`

#### Scenario: Slots from today remain covered
- **WHEN** requested slots start at or after 00:00 today in the configured timezone
- **THEN** every slot within the forecast horizon SHALL receive Open-Meteo PV data
