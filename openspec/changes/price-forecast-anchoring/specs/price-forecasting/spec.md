## MODIFIED Requirements

### Requirement: Price forecast feature engineering
The model SHALL use the following feature categories: calendar features (hour, day_of_week, month, is_weekend, is_holiday), regional wind index (from regional weather coordinates), local weather (temperature, cloud cover, solar radiation), price lags (same hour yesterday, same hour last week, trailing daily average), and `days_ahead` (integer 1-7).

Price lag features SHALL respect issue-time knowability in both directions of the pipeline:

- **Inference** SHALL query `slot_observations` when building lag features (a database session SHALL be provided to feature building), so that every lag whose source observation exists is populated with the real value. Lags whose source slot has not yet been observed SHALL be NaN because the observation is absent — not because the database was never consulted.
- **Training** SHALL only materialise a lag value when its source timestamp strictly precedes the training row's `issue_timestamp`; lags that would not have been knowable when the forecast was issued SHALL be NaN. For the trailing 24-hour average, the whole window SHALL be masked to NaN unless the window end precedes `issue_timestamp`.

#### Scenario: Calendar features extracted from target slot
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL extract hour, day_of_week, month, is_weekend, and is_holiday from the target slot timestamp

#### Scenario: Price lag features computed from historical observations
- **WHEN** building features for a forecast slot
- **THEN** the system SHALL compute price lags from `slot_observations.export_price_sek_kwh`: same hour yesterday, same hour one week ago, and trailing 24-hour average
- **AND** missing lags SHALL be filled with NaN (LightGBM handles missing values natively)

#### Scenario: Inference populates lags from the database
- **WHEN** `generate_price_forecasts` builds features for any forecast horizon
- **THEN** feature building SHALL receive a database session
- **AND** a D+1 slot whose same-hour-yesterday observation exists SHALL have a populated (non-NaN) `price_lag_1d`
- **AND** the 7-day lag SHALL be populated for any horizon whose slot−7d observation exists

#### Scenario: Unobserved lags stay NaN at inference
- **WHEN** building inference features for a D+3 slot whose same-hour-yesterday (D+2) has no observation row
- **THEN** `price_lag_1d` SHALL be NaN

#### Scenario: Training masks lags unknowable at issue time
- **WHEN** building the training dataset for a row with `issue_timestamp` T and target `slot_start` S
- **THEN** `price_lag_1d` SHALL be NaN unless `S − 1 day < T`
- **AND** `price_lag_7d` SHALL be NaN unless `S − 7 days < T`
- **AND** `price_lag_24h_avg` SHALL be NaN unless `S − 1 day < T` (window end precedes issue time)

#### Scenario: Days-ahead feature distinguishes horizons
- **WHEN** building features for a slot that is N days in the future
- **THEN** the `days_ahead` feature SHALL be set to N (integer 1-7)
