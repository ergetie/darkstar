## Purpose

Make the weather features of the Aurora models real during training, so temperature, cloud cover and shortwave radiation carry signal instead of being missing for nearly all history.

## ADDED Requirements

### Requirement: Training uses historical weather for the whole training window
Model training SHALL obtain hourly temperature, cloud cover and shortwave radiation for the full span of the training observations, at 15-minute resolution, so that weather columns are populated for every training slot Open-Meteo has data for. The historical-forecast source SHALL be preferred so that training weather matches the kind of data the live forecast supplies; the reanalysis (archive) source SHALL be used only for spans the historical-forecast source does not cover.

#### Scenario: Weather covers all history
- **WHEN** training runs with 90 days of observations and Open-Meteo is reachable
- **THEN** at least 95 % of the daylight training slots SHALL have non-missing temperature, cloud cover and shortwave radiation
- **AND** the weather columns SHALL be eligible model features

#### Scenario: Repeated training does not refetch
- **WHEN** training runs twice within the cache lifetime for the same location and window
- **THEN** the second run SHALL reuse cached weather and make no new historical request for already cached days

#### Scenario: Window spans a daylight-saving change
- **WHEN** the training window contains a clock change
- **THEN** each 15-minute weather value SHALL align with the observation of the same instant, with no duplicated or shifted slots

### Requirement: Weather fetch failure degrades gracefully
If historical weather cannot be fetched, training SHALL continue without the weather features and log a warning. Training SHALL NOT abort and SHALL NOT substitute values from unrelated columns.

#### Scenario: Open-Meteo unreachable during training
- **WHEN** the historical weather request fails or returns no data
- **THEN** a warning SHALL be logged
- **AND** the PV and load models SHALL still be trained using the remaining features

#### Scenario: Partial coverage
- **WHEN** weather is returned for only part of the window
- **THEN** slots without weather SHALL keep missing values and training SHALL proceed

### Requirement: Inference weather is unchanged
Live forecasting SHALL continue to use forecast weather. Model features and their names SHALL be identical between training and inference.

#### Scenario: Live forecast after retraining
- **WHEN** a model trained with historical weather is used for a live forecast
- **THEN** the forecast weather columns SHALL be used as inputs with the same names as in training

#### Scenario: Forecast too high or too low
- **WHEN** actual weather differs from the forecast weather in either direction (cloudier or clearer than forecast)
- **THEN** the model output SHALL follow the forecast weather input only; no retroactive correction is applied and the error is measured by the normal forecast-vs-actual comparison
