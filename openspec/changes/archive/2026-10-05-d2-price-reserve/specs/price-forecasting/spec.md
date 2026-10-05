## MODIFIED Requirements

### Requirement: Price forecast feature engineering
The model SHALL use the following feature categories: calendar features (hour, day_of_week, month, is_weekend, is_holiday), regional wind index (from regional weather coordinates), local weather (temperature, cloud cover, solar radiation), price lags (same hour yesterday, same hour last week, trailing daily average), and `days_ahead` (integer 1-7).

Price lag features SHALL respect issue-time knowability in both directions of the pipeline:

- **Inference** SHALL resolve every lag source slot from `slot_observations` and, when the slot has no observation, from the published Nordpool spot prices available at issue time (`get_known_spot_by_slot`; forecast-fallback entries are never treated as published). A database session SHALL be provided to feature building. Lags whose source slot is neither observed nor published SHALL be NaN. Each generation run SHALL record `known_prices_until`: the end (exclusive) of the last published slot it had available, or null when no published prices were available. The value is therefore also non-null for the morning run (the end of today), and training treats today's published prices as knowable, consistent with inference.
- **Training** SHALL only materialise a lag value when its source slot was knowable when the row was issued: the source slot start strictly precedes the row's `issue_timestamp`, OR the row has a non-null `known_prices_until` and the source slot starts before it. For the trailing 24-hour average, the whole window SHALL be masked to NaN unless its last slot is knowable by the same rule. Rows with null `known_prices_until` (including all rows written before this change) SHALL use the issue-timestamp rule only.

#### Scenario: Calendar features extracted from target slot
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL extract hour, day_of_week, month, is_weekend, and is_holiday from the target slot timestamp

#### Scenario: Price lag features computed from historical observations
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL compute price lags from `slot_observations.export_price_sek_kwh`, falling back to published spot prices for unobserved slots: same hour yesterday, same hour one week ago, and trailing 24-hour average
- **AND** missing lags SHALL be filled with NaN (LightGBM handles missing values natively)

#### Scenario: Inference populates lags from the database
- **WHEN** `generate_price_forecasts` builds features for any forecast horizon
- **THEN** feature building SHALL receive a database session
- **AND** a D+1 slot whose same-hour-yesterday observation exists SHALL have a populated (non-NaN) `price_lag_1d`
- **AND** the 7-day lag SHALL be populated for any horizon whose slot−7d observation exists

#### Scenario: Published D+1 prices feed D+2 lags
- **GIVEN** tomorrow's (D+1) Nordpool prices are published and not yet observed
- **WHEN** inference builds features for a D+2 slot
- **THEN** `price_lag_1d` SHALL equal the published D+1 spot for the same local hour
- **AND** the run SHALL persist `known_prices_until` equal to the end of D+1

#### Scenario: Unobserved lags stay NaN at inference
- **WHEN** building inference features for a D+3 slot whose same-hour-yesterday (D+2) has neither an observation row nor a published price
- **THEN** `price_lag_1d` SHALL be NaN

#### Scenario: Training masks lags unknowable at issue time
- **WHEN** building the training dataset for a row with `issue_timestamp` T, `known_prices_until` K (possibly null) and target `slot_start` S
- **THEN** `price_lag_1d` SHALL be NaN unless `S − 1 day < T` or (K is not null and `S − 1 day < K`)
- **AND** `price_lag_7d` SHALL be NaN unless `S − 7 days < T` or (K is not null and `S − 7 days < K`)
- **AND** `price_lag_24h_avg` SHALL be NaN unless its window end `S − 1 day` satisfies the same rule

#### Scenario: Legacy rows keep the old rule
- **WHEN** a training row has null `known_prices_until`
- **THEN** lags SHALL be masked exactly as `S − lag < T`

#### Scenario: Days-ahead feature distinguishes horizons
- **WHEN** building features for a slot that is N days in the future
- **THEN** the `days_ahead` feature SHALL be set to N (integer 1-7)

### Requirement: Price forecast scheduling
The system SHALL call `generate_price_forecasts()` on three independent schedules: once on every training cycle (regardless of whether training succeeded), once per day on a dedicated daily tick (configurable `price_forecast.daily_run_time`, default 06:00), and once per day as soon as the next day's Nordpool prices are published (the **post-publication run**). This ensures weather snapshots accumulate continuously from first install and that the afternoon planner decisions use a forecast that knows tomorrow's prices.

`generate_price_forecasts` SHALL accept the horizons to generate as `days_ahead_range` (default D+1 through D+7).

The post-publication run SHALL:
- cover D+2 through D+7 only (D+1 is published; its morning forecast rows are kept for the D+1 fallback and accuracy reporting);
- be triggered when the published prices for the whole next local day are available, checked no more often than every 10 minutes and only from 12:00 local time until 23:59;
- run at most once per local day, determined from the persisted forecast rows (a row issued today with `known_prices_until` at or after the end of tomorrow), so restarts do not cause duplicate runs;
- be skipped for that day if the next day's prices are never published, with a "waiting for publication" info log written once per local day;
- not run while another scheduler task is active (it waits for the next check).

#### Scenario: Weather snapshots run on every training cycle
- **WHEN** the training orchestrator runs a training cycle
- **THEN** `generate_price_forecasts()` SHALL be called regardless of whether price model training succeeded or was skipped

#### Scenario: Daily weather snapshot tick
- **WHEN** the daily scheduler tick fires (independent of training schedule)
- **THEN** `generate_price_forecasts()` SHALL be called to persist a fresh weather snapshot for D+1 through D+7

#### Scenario: Post-publication run after tomorrow's prices appear
- **GIVEN** price forecasting is enabled and it is 13:20 local
- **AND** tomorrow's prices were published at 13:05 and no post-publication run happened today
- **WHEN** the scheduler checks
- **THEN** `generate_price_forecasts()` SHALL run for D+2..D+7 with published D+1 prices available to lag features

#### Scenario: Restart after the post-publication run
- **GIVEN** today's post-publication run already persisted rows with `known_prices_until` at the end of tomorrow
- **WHEN** the service restarts at 15:00 and the scheduler checks
- **THEN** no second post-publication run SHALL happen today

#### Scenario: Late or missing publication
- **GIVEN** tomorrow's prices are still unpublished at 16:00
- **WHEN** the scheduler checks every 10 minutes
- **THEN** the run SHALL happen at the first check after publication
- **AND** if prices are never published that day, no post-publication run SHALL happen and the next morning run SHALL proceed normally

### Requirement: Price forecast persistence
Each price forecast record SHALL be persisted to a `price_forecasts` table in `planner_learning.db`. Each record SHALL store the weather feature values used at prediction time alongside the forecast output to enable honest training, and the run's `known_prices_until` (nullable timestamp). Records without spot predictions (weather-only rows) are valid and SHALL be stored with null spot columns.

Persistence SHALL be overwrite-on-save keyed on `(slot_start, days_ahead)`: when a generation run persists a forecast for a `(slot_start, days_ahead)` pair that already has a stored row, the write SHALL replace the existing row rather than append an additional one. The replacing row SHALL carry the new `issue_timestamp`, `known_prices_until` and the newly computed weather/spot values. Consequently, immediately after any single generation run completes, at most one row SHALL exist per `(slot_start, days_ahead)` pair for the slots that run covered. No database-level UNIQUE constraint is required; the behavior SHALL be enforced by the write path. The existing startup duplicate-cleanup SHALL be retained as a backstop and legacy-data sweep. The `known_prices_until` column SHALL be added by an additive Alembic migration; existing rows SHALL keep null.

#### Scenario: Forecast record stores weather inputs
- **WHEN** a price forecast is generated for a target slot
- **THEN** the persisted record SHALL include: target slot timestamp, forecast issue timestamp, days_ahead, predicted spot price (p10/p50/p90), the weather feature values (regional wind index, temperature, cloud cover, radiation) used at prediction time, and `known_prices_until`

#### Scenario: Forecast records queryable for training
- **WHEN** the training pipeline needs historical forecast-weather pairs
- **THEN** it SHALL query `price_forecasts` joined with `slot_observations` (on target slot) to get (weather_at_forecast_time, actual_spot_price) training pairs together with `issue_timestamp` and `known_prices_until`
- **AND** rows with null spot columns SHALL be included in this join (the spot columns are not training features)

#### Scenario: Weather-only record stored during cold start
- **WHEN** a forecast row is persisted and no model was available at issue time
- **THEN** the record SHALL store all weather feature columns with their actual values
- **AND** spot_p10, spot_p50, and spot_p90 SHALL be null

#### Scenario: Re-running generation overwrites the prior forecast for a slot
- **WHEN** a generation run persists a forecast for a `(slot_start, days_ahead)` pair for which a row already exists
- **THEN** the existing row SHALL be replaced (not duplicated)
- **AND** the resulting row SHALL hold the new run's `issue_timestamp`, `known_prices_until` and newly computed spot/weather values

#### Scenario: No duplicate rows accrue across repeated runs
- **WHEN** two generation runs in succession both cover the same `(slot_start, days_ahead)` pairs
- **THEN** after the second run completes there SHALL be exactly one row per such `(slot_start, days_ahead)` pair
- **AND** that row SHALL correspond to the later run

#### Scenario: Migration on an existing database
- **WHEN** the migration runs on a database with existing `price_forecasts` rows
- **THEN** the column SHALL be added as nullable and every existing row SHALL have null `known_prices_until`
