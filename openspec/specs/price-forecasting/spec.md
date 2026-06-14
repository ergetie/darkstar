## Purpose

Enable machine learning-based forecasting of Nordpool electricity spot prices to provide price outlooks and enable D+1 fallback before day-ahead auction publication.

## Requirements

### Requirement: Price forecast model training
The system SHALL train a LightGBM quantile regression model (p10/p50/p90) to predict raw Nordpool spot prices for horizons D+1 through D+7. The training target SHALL be `slot_observations.export_price_sek_kwh` (raw spot price, no fees/taxes). The model SHALL use a single model with `days_ahead` as a feature rather than per-horizon models.

#### Scenario: Model trains on paired price and weather data
- **WHEN** the training pipeline runs and sufficient paired (price + weather) data exists above the minimum sample threshold
- **THEN** the system SHALL train a LightGBM quantile regression model using historical forecast weather inputs paired with actual spot prices

#### Scenario: Cold-start gating prevents training with insufficient data
- **WHEN** the training pipeline runs and paired data is below the minimum sample threshold
- **THEN** the system SHALL skip price model training and log a message indicating insufficient data
- **AND** no price forecast model file SHALL be written

#### Scenario: Training follows existing schedule
- **WHEN** the Aurora training schedule triggers (configured `run_days` and `run_time`)
- **THEN** the price model SHALL train alongside the existing load and PV models

### Requirement: Price forecast feature engineering
The model SHALL use the following feature categories: calendar features (hour, day_of_week, month, is_weekend, is_holiday), regional wind index (from regional weather coordinates), local weather (temperature, cloud cover, solar radiation), price lags (same hour yesterday, same hour last week, trailing daily average), and `days_ahead` (integer 1-7).

#### Scenario: Calendar features extracted from target slot
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL extract hour, day_of_week, month, is_weekend, and is_holiday from the target slot timestamp

#### Scenario: Price lag features computed from historical observations
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL compute price lags from `slot_observations.export_price_sek_kwh`: same hour yesterday, same hour one week ago, and trailing 24-hour average
- **AND** missing lags SHALL be filled with NaN (LightGBM handles missing values natively)

#### Scenario: Days-ahead feature distinguishes horizons
- **WHEN** building features for a slot that is N days in the future
- **THEN** the `days_ahead` feature SHALL be set to N (integer 1-7)

### Requirement: Price forecast inference
The system SHALL generate price forecasts for D+1 through D+7 at 15-minute slot resolution. D+1 forecasts SHALL serve as fallback before the ~13:00 CET Nordpool day-ahead auction. Once real Nordpool D+1 prices are available, they SHALL take precedence over the D+1 forecast. When no trained model exists, the system SHALL still fetch regional weather and persist rows with null spot prediction columns to accumulate training data.

`get_price_forecasts_from_db` SHALL return exactly one record per `slot_start` value. When multiple DB rows share the same `slot_start` (due to duplicate writes), the function SHALL keep the row with the latest `issue_timestamp`; if rows also tie on `issue_timestamp`, any single row for that slot is acceptable. This guarantee applies regardless of whether `days_ahead` filtering is active.

`get_d1_price_forecast_fallback` SHALL deduplicate its return value on `slot_start` before returning, so that callers never receive two entries with the same slot timestamp. `get_d1_price_forecast_fallback` SHALL filter out any slots whose `slot_start` date is on or before the current date (today), returning only slots that are strictly in the future (tomorrow or later).

`_process_nordpool_data` SHALL deduplicate the assembled entry list by `start_time` before returning, keeping the first occurrence of each timestamp. Because real Nordpool entries are always prepended before fallback entries, this ensures real prices take precedence.

#### Scenario: Daily forecast generation
- **WHEN** the forecast pipeline runs and a trained price model exists
- **THEN** the system SHALL generate p10/p50/p90 spot price forecasts for all 15-minute slots from D+1 through D+7

#### Scenario: D+1 fallback before auction
- **WHEN** a downstream consumer requests prices and real Nordpool D+1 prices are not yet available (before ~13:00 CET)
- **THEN** the system SHALL provide the D+1 price forecast as a fallback
- **AND** the system SHALL only return rows where spot_p50 is not null

#### Scenario: D+1 fallback excludes today and past slots
- **WHEN** `get_d1_price_forecast_fallback` retrieves forecast rows from the DB
- **THEN** the function SHALL discard any rows whose `slot_start` date is today or earlier
- **AND** the returned list SHALL contain only slots for tomorrow or later

#### Scenario: Real prices replace D+1 forecast
- **WHEN** real Nordpool D+1 prices become available (after auction publication)
- **THEN** the system SHALL use real prices for D+1 instead of the forecast

#### Scenario: Weather accumulation without trained model
- **WHEN** the forecast pipeline runs and no trained price model exists
- **THEN** the system SHALL still fetch regional weather data and build feature rows for D+1 through D+7
- **AND** the system SHALL persist those rows with spot_p10, spot_p50, and spot_p90 set to null
- **AND** the system SHALL NOT return these rows to downstream consumers as price forecasts

#### Scenario: DB query deduplicates by slot_start
- **WHEN** `get_price_forecasts_from_db` is called and the DB contains multiple rows for the same `slot_start` with the same `days_ahead`
- **THEN** the function SHALL return exactly one row for that `slot_start`
- **AND** the returned row SHALL have the latest `issue_timestamp` among all candidates

#### Scenario: Fallback deduplicates before returning
- **WHEN** `get_d1_price_forecast_fallback` retrieves rows from the DB and two rows share the same `slot_start`
- **THEN** the function SHALL return only one entry per `slot_start`
- **AND** the returned list SHALL have no duplicate `slot_start` values

#### Scenario: Assembled price data has no duplicate timestamps
- **WHEN** `_process_nordpool_data` assembles the final price entry list from Nordpool and fallback sources
- **THEN** the returned list SHALL contain at most one entry per `start_time` value
- **AND** when two sources provide the same `start_time`, the entry that appeared first in the input (real Nordpool) SHALL be kept

### Requirement: Price forecast scheduling
The system SHALL call `generate_price_forecasts()` on two independent schedules: once on every training cycle (regardless of whether training succeeded), and once per day on a dedicated daily tick (e.g., 06:00). This ensures weather snapshots accumulate continuously from first install, enabling the model to train within approximately one week.

#### Scenario: Weather snapshots run on every training cycle
- **WHEN** the training orchestrator runs a training cycle
- **THEN** `generate_price_forecasts()` SHALL be called regardless of whether price model training succeeded or was skipped

#### Scenario: Daily weather snapshot tick
- **WHEN** the daily scheduler tick fires (independent of training schedule)
- **THEN** `generate_price_forecasts()` SHALL be called to persist a fresh weather snapshot for D+1 through D+7

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

### Requirement: Import/export price derivation
At inference time, forecasted import and export prices SHALL be derived from the raw spot price prediction by applying the same fee/VAT/tax logic used in `backend/core/prices.py`. The model SHALL NOT predict import prices directly.

#### Scenario: Import price derived from spot forecast
- **WHEN** a downstream consumer needs a forecasted import price
- **THEN** the system SHALL calculate it as: `(spot_forecast + grid_transfer_fee + energy_tax) * (1 + vat_percent/100)` using current config values

#### Scenario: Export price equals spot forecast
- **WHEN** a downstream consumer needs a forecasted export price
- **THEN** the system SHALL return the raw spot price forecast directly

### Requirement: Price forecast config toggle
A `price_forecast.enabled` config option SHALL exist (disabled by default). When disabled, no price forecasts SHALL be exposed to downstream consumers. Training and persistence MAY still occur to accumulate data.

#### Scenario: Toggle disabled by default
- **WHEN** a fresh system starts with default config
- **THEN** `price_forecast.enabled` SHALL be `false`

#### Scenario: Toggle gates downstream consumption
- **WHEN** `price_forecast.enabled` is `false`
- **THEN** API endpoints serving price forecasts to downstream consumers SHALL return empty/null results
- **AND** training and internal forecast persistence MAY continue

#### Scenario: Toggle enables downstream consumption
- **WHEN** `price_forecast.enabled` is `true` and a trained model exists with sufficient data
- **THEN** API endpoints SHALL return price forecast data to downstream consumers

### Requirement: Price forecast API endpoint
The backend SHALL expose a REST API endpoint for retrieving price forecasts. The endpoint SHALL return forecast data for D+1 through D+7 including p10/p50/p90 spot prices and derived import/export prices per 15-minute slot.

#### Scenario: Endpoint returns forecast data
- **WHEN** a client requests the price forecast endpoint and `price_forecast.enabled` is `true` and forecasts exist
- **THEN** the response SHALL include an array of slot records with: slot timestamp, spot_p10, spot_p50, spot_p90, import_p50, export_p50, and days_ahead

#### Scenario: Endpoint returns empty when disabled
- **WHEN** a client requests the price forecast endpoint and `price_forecast.enabled` is `false`
- **THEN** the response SHALL return an empty forecast array with a status indicating forecasting is disabled

#### Scenario: Endpoint returns empty when no model
- **WHEN** a client requests the price forecast endpoint and no trained model exists
- **THEN** the response SHALL return an empty forecast array with a status indicating insufficient training data

### Requirement: D+1 fallback null safety
The D+1 fallback query SHALL filter out weather-only (null-prediction) rows before returning results to the planner. A row with a null spot_p50 SHALL never be served as a price forecast to downstream consumers. The query SHALL return at most one forecast record per `slot_start`, preferring the row with the latest `issue_timestamp` when multiple forecast runs exist for the same slot.

#### Scenario: Fallback excludes null-prediction rows
- **WHEN** `get_d1_price_forecast_fallback()` queries the database and weather-only rows exist for D+1
- **THEN** those rows SHALL be excluded from the returned results
- **AND** if no non-null D+1 forecast rows exist, the function SHALL return None

#### Scenario: Fallback deduplicates by slot_start
- **WHEN** `get_d1_price_forecast_fallback()` queries the database and multiple forecast runs exist for the same `slot_start` (different `issue_timestamp`)
- **THEN** the query SHALL return only the row with the latest `issue_timestamp` per `slot_start`
- **AND** the returned list SHALL contain at most one record per unique `slot_start`

#### Scenario: Fallback returns correct count after dedup
- **WHEN** `get_d1_price_forecast_fallback()` queries the database with `limit=96` and 48 unique slots each have 2 forecast runs (96 total rows)
- **THEN** the function SHALL return exactly 48 records (one per unique slot, each the latest run)
