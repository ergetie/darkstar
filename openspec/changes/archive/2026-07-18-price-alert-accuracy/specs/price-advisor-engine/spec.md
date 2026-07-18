# Price Advisor Engine — Delta

## MODIFIED Requirements

### Requirement: Price-aware advice rules in analyst endpoint
The existing `GET /api/analyst/advice` endpoint SHALL include price-related advice items with `category: "price"` when `price_forecast.enabled` is `true` and forecast data is available.

The "today" reference price used by the rules SHALL be the average of today's actual day-ahead spot prices (from the Nordpool price feed), never a forecast-derived proxy such as the D+1 outlook average. When today's actual prices are unavailable, no price advice items SHALL be emitted.

#### Scenario: Cheapest day ahead
- **WHEN** any day in D+1 through D+7 has an average spot p50 that is 30% or more below today's actual average spot price
- **AND** the absolute drop is at least 0.15 SEK/kWh
- **THEN** the advisor SHALL emit an advice item: `category: "price"`, `priority: "info"`, with a message indicating the percentage drop and which day (e.g., "Prices drop ~40% on Thursday. Consider deferring heavy loads.")

#### Scenario: Cheapest day ahead suppressed for tiny absolute drops
- **WHEN** a day in D+1 through D+7 is 30% or more below today's actual average spot price
- **AND** the absolute drop is less than 0.15 SEK/kWh
- **THEN** no "cheapest day ahead" advice item SHALL be emitted

#### Scenario: Prices rising short-term
- **WHEN** every day from D+1 through D+3 has a higher average spot p50 than today's actual average spot price
- **THEN** the advisor SHALL emit an advice item: `category: "price"`, `priority: "info"`, with a message indicating today is the cheapest day in the next 3 days

#### Scenario: Prices rising rule is able to fire
- **WHEN** today's actual average is 0.50 SEK/kWh and D+1, D+2, D+3 forecast daily averages are all above 0.50 SEK/kWh
- **THEN** the "prices rising" advice item SHALL be emitted (regression guard: with the former D+1-as-today proxy this rule could never fire)

#### Scenario: Cheap overnight window
- **WHEN** the average forecast spot p50 over the slots from today 22:00 to tomorrow 06:00 (local time) is 25% or more below tomorrow's full-day average spot p50
- **THEN** the advisor SHALL emit an advice item: `category: "price"`, `priority: "info"`, with a message indicating the overnight window is cheapest
- **AND** the comparison SHALL be computed from the actual slot values in that window, not from the day's minimum slot value

#### Scenario: Solar midday hours cheapest instead of overnight
- **WHEN** the overnight window does not qualify (less than 25% below tomorrow's daily average)
- **AND** the average forecast spot p50 over tomorrow's 10:00–16:00 (local time) slots is 25% or more below tomorrow's full-day average
- **THEN** the advisor SHALL emit an advice item: `category: "price"`, `priority: "info"`, with a message indicating the midday solar hours are cheapest
- **AND** no overnight advice item SHALL be emitted

#### Scenario: Single cheap slot does not trigger overnight advice
- **WHEN** tomorrow's minimum 15-minute slot is more than 25% below tomorrow's daily average
- **AND** the 22:00–06:00 window average is less than 25% below tomorrow's daily average
- **THEN** no overnight advice item SHALL be emitted (regression guard against the former min-slot heuristic that fired on 96% of replayed days)

#### Scenario: Price forecast disabled
- **WHEN** `price_forecast.enabled` is `false`
- **THEN** no price advice items SHALL be included in the response
- **AND** existing non-price advice (risk, mode, battery) SHALL continue to work unchanged

#### Scenario: No forecast data available
- **WHEN** `price_forecast.enabled` is `true` but no price forecast records exist
- **THEN** no price advice items SHALL be included in the response

#### Scenario: Today's actual prices unavailable
- **WHEN** `price_forecast.enabled` is `true` but today's actual day-ahead prices cannot be fetched
- **THEN** no price advice items SHALL be included in the response
- **AND** the endpoint SHALL still return successfully with the remaining advice categories
