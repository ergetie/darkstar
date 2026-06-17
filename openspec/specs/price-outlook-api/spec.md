## Purpose

Provide aggregated daily price outlook summaries for the Weekly Outlook UI widget, enabling users to see upcoming electricity price trends and make informed decisions about energy usage.

## Requirements

### Requirement: Daily price outlook endpoint
The system SHALL provide a `GET /api/price-forecast/outlook` endpoint that returns aggregated daily price summaries for D+1 through D+7, suitable for the Weekly Outlook UI widget.

#### Scenario: Forecast enabled with available data
- **WHEN** `price_forecast.enabled` is `true` and price forecast records exist in the database
- **THEN** the endpoint returns a JSON object with `enabled: true`, a `days` array of 7 daily summaries, a `reference_avg` (14-day trailing average spot price), and `status: "ok"`

#### Scenario: Each daily summary contains required fields
- **WHEN** the endpoint returns a day entry
- **THEN** it SHALL include `date` (ISO date string), `day_label` (short weekday name), `days_ahead` (integer 1-7), `avg_spot_p50` (daily mean of p50 forecasts), `avg_spot_p10`, `avg_spot_p90`, `min_hour_p50` (cheapest hour), `max_hour_p50` (most expensive hour), `level` (string), and `confidence` (string)

#### Scenario: Price level classification
- **WHEN** a day's `avg_spot_p50` is below 85% of `reference_avg`
- **THEN** its `level` SHALL be `"cheap"`
- **WHEN** a day's `avg_spot_p50` is between 85% and 115% of `reference_avg`
- **THEN** its `level` SHALL be `"normal"`
- **WHEN** a day's `avg_spot_p50` is above 115% of `reference_avg`
- **THEN** its `level` SHALL be `"expensive"`

#### Scenario: Confidence classification by horizon
- **WHEN** `days_ahead` is 1 or 2
- **THEN** `confidence` SHALL be `"high"`
- **WHEN** `days_ahead` is 3 or 4
- **THEN** `confidence` SHALL be `"medium"`
- **WHEN** `days_ahead` is 5, 6, or 7
- **THEN** `confidence` SHALL be `"low"`

#### Scenario: Forecast disabled
- **WHEN** `price_forecast.enabled` is `false`
- **THEN** the endpoint returns `{"enabled": false, "days": [], "status": "disabled"}`

#### Scenario: No forecast data available
- **WHEN** `price_forecast.enabled` is `true` but no price forecast records exist
- **THEN** the endpoint returns `{"enabled": true, "days": [], "status": "no_data"}`

### Requirement: Trailing average handles cold start
The `reference_avg` field SHALL be computed from the most recent 14 days of actual spot prices in `slot_observations.export_price_sek_kwh`. If fewer than 14 days are available, the system SHALL use whatever history exists (minimum 2 days). If fewer than 2 days of price history exist, the response SHALL omit `reference_avg` (set to `null`) and all day entries SHALL have `level` set to `"unknown"`.

#### Scenario: Full 14-day history available
- **WHEN** at least 14 days of price observations exist
- **THEN** `reference_avg` is the mean of `export_price_sek_kwh` over the most recent 14 days

#### Scenario: Partial history (2-13 days)
- **WHEN** between 2 and 13 days of price observations exist
- **THEN** `reference_avg` is computed from available days

#### Scenario: Insufficient history (less than 2 days)
- **WHEN** fewer than 2 days of price observations exist
- **THEN** `reference_avg` is `null` and all `level` fields are `"unknown"`

### Requirement: Endpoint follows router conventions
The endpoint SHALL be added to the price forecast router created by Module 1 (`backend/api/routers/price_forecast.py`), following existing router structure conventions (explicit prefix, tags).

#### Scenario: Router registration
- **WHEN** the application starts
- **THEN** the `/api/price-forecast/outlook` endpoint is accessible and returns valid JSON

### Requirement: Daily outlook query is bounded to the latest forecast run
The daily price outlook query SHALL read only the rows belonging to the most recent forecast run, identified by the maximum `issue_timestamp` in `price_forecasts`, rather than scanning the entire forecast history. The endpoint's response fields, level/confidence classifications, and statuses SHALL remain unchanged.

#### Scenario: Only the latest run is read
- **WHEN** the outlook query executes against a `price_forecasts` table containing many historical forecast runs
- **THEN** only rows with the maximum `issue_timestamp` and `days_ahead` between 1 and 7 are read
- **AND** no per-row processing is performed on rows from older runs

#### Scenario: Output is unchanged from full-history processing
- **WHEN** the latest forecast run contains a complete D+1 through D+7 set
- **THEN** the returned `days` array, `reference_avg`, classifications, and `status` are identical to the previously specified outlook behavior

#### Scenario: Latest run empty or missing
- **WHEN** no forecast rows exist or the latest run yields no usable days
- **THEN** the endpoint returns the existing `no_data` response (`enabled: true`, empty `days`, `status: "no_data"`)
