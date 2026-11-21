## ADDED Requirements

### Requirement: Shared price forecast accuracy computation
The endpoint and the planner SHALL obtain D+1 price forecast accuracy from one shared function (database fetch plus pure computation) that takes the forecast horizon (`days_ahead`, default 1), so their numbers never diverge. The endpoint always reports horizon 1.

#### Scenario: Endpoint output unchanged
- **WHEN** the endpoint is called after this change with the same stored data as before
- **THEN** the response SHALL be identical to the previous response (`d1_mae`, `d1_bias` rounded to 4 decimals, `sample_days`, `status`)

#### Scenario: Endpoint and planner agree
- **WHEN** the same database is read by the endpoint and by the planner's reserve input builder
- **THEN** the bias and MAE used by the planner SHALL equal the endpoint's `d1_bias` and `d1_mae` (before rounding)

#### Scenario: Metric definitions
- **GIVEN** the same 7-day D+1 window and join the endpoint uses today, with `export_price_sek_kwh` as raw spot in SEK/kWh
- **WHEN** the accuracy is computed for error `e = spot_p50 - export_price_sek_kwh` per slot
- **THEN** `bias` SHALL be mean(`e`), `mae` SHALL be mean(`|e|`), `debiased_mae` SHALL be mean(`|e - bias|`) and `sample_days` SHALL be the number of distinct dates in `slot_start`

#### Scenario: De-biased MAE excludes constant offset
- **GIVEN** every paired slot has forecast error exactly +0.30 SEK/kWh
- **WHEN** the accuracy is computed
- **THEN** `bias` SHALL be 0.30, `mae` SHALL be 0.30 and `debiased_mae` SHALL be 0

#### Scenario: Insufficient data
- **WHEN** fewer than 2 sample days of paired data exist
- **THEN** the status SHALL be `insufficient_data`

#### Scenario: Other horizons use the same function
- **WHEN** the planner requests accuracy for `days_ahead = 2`
- **THEN** the same function and join SHALL be used with the `days_ahead` bound to 2, and the endpoint's result for `days_ahead = 1` SHALL be unaffected
