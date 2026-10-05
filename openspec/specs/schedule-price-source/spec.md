# schedule-price-source Specification

## Purpose
Tells the frontend which schedule slots rest on published Nordpool prices and which on forecasts, so the chart can mark estimated prices.
## Requirements
### Requirement: Schedule slots state whether their price is published or forecast
Every slot returned by `GET /api/schedule` and `GET /api/schedule/today_with_history` SHALL carry a `price_source` field. It SHALL be `"nordpool"` when a published (not forecast-fallback) price exists for the slot's local start time, and `"forecast"` otherwise, including slots beyond the published price horizon where the planner used forecast prices. Price entries without a source SHALL count as published. If the price overlay is unavailable, the endpoint SHALL still respond and slots MAY lack the field.

#### Scenario: Published slot
- **WHEN** the price feed has a Nordpool price for a slot's start time
- **THEN** the slot has `price_source` "nordpool"

#### Scenario: Forecast fallback slot
- **WHEN** the price feed has only a forecast price for a slot
- **THEN** the slot has `price_source` "forecast"

#### Scenario: Slot beyond the published horizon
- **WHEN** a slot starts after the last published price
- **THEN** the slot has `price_source` "forecast"

#### Scenario: Both schedule endpoints tag slots
- **WHEN** a client calls `/api/schedule` or `/api/schedule/today_with_history`
- **THEN** each slot in the response has `price_source`

#### Scenario: Price overlay fails
- **WHEN** the price overlay raises an error
- **THEN** the endpoint still returns the schedule, without `price_source` tags
