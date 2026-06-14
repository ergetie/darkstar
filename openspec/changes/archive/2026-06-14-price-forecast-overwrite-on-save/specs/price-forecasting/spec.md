## MODIFIED Requirements

### Requirement: Price forecast persistence
Each price forecast record SHALL be persisted to a `price_forecasts` table in `planner_learning.db`. Each record SHALL store the weather feature values used at prediction time alongside the forecast output to enable honest training. Records without spot predictions (weather-only rows) are valid and SHALL be stored with null spot columns.

Persistence SHALL be overwrite-on-save keyed on `(slot_start, days_ahead)`: when a generation run persists a forecast for a `(slot_start, days_ahead)` pair that already has a stored row, the write SHALL replace the existing row rather than append an additional one. The replacing row SHALL carry the new `issue_timestamp` and the newly computed weather/spot values. Consequently, immediately after any single generation run completes, at most one row SHALL exist per `(slot_start, days_ahead)` pair for the slots that run covered. No database-level UNIQUE constraint is required; the behavior SHALL be enforced by the write path. The existing startup duplicate-cleanup SHALL be retained as a backstop and legacy-data sweep.

#### Scenario: Forecast record stores weather inputs
- **WHEN** a price forecast is generated for a target slot
- **THEN** the persisted record SHALL include: target slot timestamp, forecast issue timestamp, days_ahead, predicted spot price (p10/p50/p90), and the weather feature values (regional wind index, temperature, cloud cover, radiation) used at prediction time

#### Scenario: Forecast records queryable for training
- **WHEN** the training pipeline needs historical forecast-weather pairs
- **THEN** it SHALL query `price_forecasts` joined with `slot_observations` (on target slot) to get (weather_at_forecast_time, actual_spot_price) training pairs
- **AND** rows with null spot columns SHALL be included in this join (the spot columns are not training features)

#### Scenario: Weather-only record stored during cold start
- **WHEN** a forecast row is persisted and no model was available at issue time
- **THEN** the record SHALL store all weather feature columns with their actual values
- **AND** spot_p10, spot_p50, and spot_p90 SHALL be null

#### Scenario: Re-running generation overwrites the prior forecast for a slot
- **WHEN** a generation run persists a forecast for a `(slot_start, days_ahead)` pair for which a row already exists
- **THEN** the existing row SHALL be replaced (not duplicated)
- **AND** the resulting row SHALL hold the new run's `issue_timestamp` and newly computed spot/weather values

#### Scenario: No duplicate rows accrue across repeated runs
- **WHEN** two generation runs in succession both cover the same `(slot_start, days_ahead)` pairs
- **THEN** after the second run completes there SHALL be exactly one row per such `(slot_start, days_ahead)` pair
- **AND** that row SHALL correspond to the later run
