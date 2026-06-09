## Purpose

The ML forecast pipeline integrity capability ensures correctness throughout the machine-learning forecast pipeline: feature symmetry between training and inference, monotonic quantile bands, accurate model evaluation, safe input handling, proper Open-Meteo interpolation, and fail-loud behaviour when inputs are missing or degraded.

## Requirements

### Requirement: Training and inference use an identical feature set
The training system SHALL materialise the same feature columns that inference expects, regardless of whether external weather data is available at training time, so a model can always be served without a feature-count mismatch.

#### Scenario: Model trained during a weather-API outage
- **WHEN** a model is trained while weather data is unavailable (empty `weather_df`)
- **THEN** the training feature matrix SHALL still include all weather feature columns (`temp_c`, `cloud_cover_pct`, `shortwave_radiation_w_m2`), NaN-filled
- **AND** the trained model's feature list SHALL match the feature list inference builds

#### Scenario: Inference against a feature-mismatched model
- **WHEN** a loaded model's persisted feature names do not match the feature set inference builds
- **THEN** the system SHALL log a warning and fall back to the Open-Meteo baseline forecast
- **AND** SHALL NOT mis-map columns or raise an unhandled LightGBM error

### Requirement: Quantile forecasts are monotonic
The forecast system SHALL guarantee `p10 ≤ p50 ≤ p90` for every stored, read, and aggregated quantile band, for both load and PV.

#### Scenario: Crossed quantiles repaired before storage
- **WHEN** the independently-trained quantile models produce a slot where p10 > p50 or p50 > p90
- **THEN** the three values SHALL be reordered into non-decreasing order before being persisted

#### Scenario: Bands repaired on read
- **WHEN** a stored band is read for planning or daily aggregation
- **THEN** the returned values SHALL satisfy `p10 ≤ p50 ≤ p90`

#### Scenario: Valid bands are unchanged
- **WHEN** a band already satisfies `p10 ≤ p50 ≤ p90`
- **THEN** the repair SHALL leave its values unchanged

### Requirement: Model evaluation mirrors the live inference pipeline
The evaluation system SHALL score the PV model on the same basis the model is served, including the residual feature set and the Open-Meteo baseline reconstruction, so reported forecast-quality reflects real behavior.

#### Scenario: PV residual model evaluated correctly
- **WHEN** the evaluator scores the PV model
- **THEN** it SHALL build the same feature set as inference (including `physics_forecast_kwh`)
- **AND** SHALL add the Open-Meteo baseline back to the residual prediction before comparing to actuals

#### Scenario: All quantiles evaluated
- **WHEN** forecast quality is computed
- **THEN** the evaluation SHALL cover the p10/p50/p90 quantiles, not the p50 alias alone

### Requirement: Inputs are never substituted with unrelated values
The forecast system SHALL NOT fill a missing input column with values from an unrelated column.

#### Scenario: Missing temperature in the baseline path
- **WHEN** the `baseline_7_day_avg` aggregation runs and history has no `temp_c` column
- **THEN** the `temp_c` field SHALL be filled with a neutral missing value (NaN), NOT with `load_kwh` values

### Requirement: Missing baseline slots are interpolated, not back-filled from home-grown physics
The forecast system SHALL fill a missing Open-Meteo baseline slot (within an otherwise-successful fetch) by interpolating from neighbouring valid slots, and SHALL NOT fall back to the home-grown physics estimate.

#### Scenario: Single missing slot between valid slots
- **WHEN** the Open-Meteo baseline is missing (NaN) for a slot that has valid Open-Meteo values before and after it
- **THEN** the slot SHALL be filled by interpolation between those neighbouring values

#### Scenario: Missing slot with no valid neighbour
- **WHEN** the Open-Meteo baseline is missing for a slot and no valid neighbouring slot exists
- **THEN** the slot SHALL be filled with 0, NOT the home-grown physics estimate

### Requirement: Missing ML inputs fail loud
The forecast system SHALL emit a warning when an input fetch fails and a fallback default is used, so degraded forecasts are diagnosable.

#### Scenario: Config load fails
- **WHEN** reading `config.yaml` for the ML pipeline raises an error
- **THEN** the system SHALL log a warning identifying the failure before returning the default empty config

#### Scenario: Context-feature fetch fails
- **WHEN** a Home-Assistant history fetch for a context feature fails
- **THEN** the system SHALL log a warning before returning the empty fallback series
