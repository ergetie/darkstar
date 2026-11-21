## ADDED Requirements

### Requirement: Price reserve uses de-biased forecast prices
The price reserve SHALL correct every forecast-sourced slot it uses with the rolling bias of that slot's own horizon, so known and unseen windows are on the same basis. Real (`nordpool`) slots and the solver's price series SHALL NOT be adjusted.

#### Scenario: Which slots are corrected
- **WHEN** the reserve inputs are built
- **THEN** unseen-window slots SHALL use the bias of the `days_ahead` of the forecast row used, and known-window slots with `price_source == "forecast"` SHALL use the bias of their carried `forecast_days_ahead` (horizon 1 when the key is absent)
- **AND** bias is the mean of `spot_p50 - actual spot` from the shared accuracy function, and negative resulting prices SHALL NOT be clamped

#### Scenario: Unseen window is corrected
- **GIVEN** a bias of +0.38 SEK/kWh for the slot's horizon over at least 2 sample days
- **WHEN** the unseen-window prices are built
- **THEN** each forecast spot SHALL be reduced by 0.38 SEK/kWh before conversion with VAT, tax and transfer fee

#### Scenario: Pre-publication known window is corrected too
- **GIVEN** tomorrow's prices are not yet published, so the known window holds real prices for today plus D+1 slots with `price_source == "forecast"`, and the unseen window is D+2
- **AND** both forecasts are biased by the measured bias of their horizons
- **WHEN** the reserve is computed
- **THEN** the forecast-sourced known slots SHALL be reduced by `bias * (1 + VAT)` in import terms, the unseen slots SHALL be corrected with their own horizon's bias, and real today slots SHALL be unchanged
- **AND** a gap that exists only because of the forecast bias SHALL neither create nor suppress a reserve

#### Scenario: Pre-issue period (00:00 to the daily forecast issue)
- **GIVEN** known-window forecast slots carry `forecast_days_ahead = 2` and unseen slots come from rows with `days_ahead = 3`
- **WHEN** the reserve is computed
- **THEN** known forecast slots SHALL use horizon-2 bias, unseen slots horizon-3 bias, with the D+1 then no-correction fallback per slot

#### Scenario: After the daily issue, before publication
- **GIVEN** known-window forecast slots carry `forecast_days_ahead = 1` and unseen slots have `days_ahead = 2`
- **WHEN** the reserve is computed
- **THEN** known forecast slots SHALL use horizon-1 bias and unseen slots horizon-2 bias

#### Scenario: Post-publication behaviour
- **GIVEN** tomorrow's prices are published, so the known window contains only real prices
- **WHEN** the reserve is computed
- **THEN** only the unseen window SHALL be corrected, as before

#### Scenario: Horizon-matched accuracy
- **GIVEN** unseen slots whose latest forecast row has `days_ahead = 2`
- **WHEN** accuracy is loaded
- **THEN** bias and typical error SHALL come from `days_ahead = 2` pairs of the 7-day window
- **AND** if that horizon has fewer than 2 sample days, D+1 accuracy SHALL be used, and if that is unavailable too, those slots SHALL NOT be corrected

#### Scenario: Biased forecast with small apparent gap
- **GIVEN** a forecast biased by +0.38 whose unseen-day cost exceeds the known cost by 0.24 only because of the bias
- **WHEN** the reserve is computed
- **THEN** the reserve SHALL be 0 kWh

## MODIFIED Requirements

### Requirement: Risk-dependent profitability threshold
The base profitability threshold (SEK per delivered kWh) SHALL depend on `s_index.risk_appetite`: 1 → 0.20, 2 → 0.15, 3 → 0.10, 4 → 0.05, 5 → 0.00. Unknown values SHALL use the risk-3 threshold. The **effective** activation threshold SHALL be `max(base threshold, typical forecast error)`, where typical forecast error is the largest de-biased MAE (mean of `|forecast error - bias|` over the 7-day window of the shared accuracy function) among the horizons of the forecast-sourced slots in use converted to the import-price domain with the marginal factor of the user's pricing configuration (`1 + VAT`). The typical error is 0 when accuracy data is unavailable.

#### Scenario: Cautious user needs a larger margin
- **GIVEN** `gain_h = 0.12` SEK/kWh for every candidate slot and no forecast accuracy data
- **WHEN** risk appetite is 1
- **THEN** the reserve SHALL be 0 kWh
- **AND** with risk appetite 3 the same inputs SHALL produce a positive reserve

#### Scenario: Gap smaller than typical forecast error
- **GIVEN** risk appetite 3 (base 0.10) and a typical forecast error of 0.20 SEK/kWh in import terms
- **WHEN** the gap between the known and unseen-day cost is 0.15 SEK/kWh
- **THEN** the effective threshold SHALL be 0.20 and the reserve SHALL be 0 kWh with reason `"below_threshold"`

#### Scenario: Accurate forecast behaves as before
- **GIVEN** risk appetite 3, bias 0 and typical error 0.02 SEK/kWh
- **WHEN** the same 0.15 SEK/kWh gap is evaluated
- **THEN** the effective threshold SHALL be 0.10 and the reserve SHALL be positive, as before this change

#### Scenario: Large real gap still reserves
- **GIVEN** a typical error of 0.20 SEK/kWh
- **WHEN** the gap is 0.60 SEK/kWh
- **THEN** the reserve SHALL be positive

#### Scenario: Boundary at the effective threshold
- **WHEN** the gain equals the effective threshold exactly
- **THEN** the reserve SHALL be 0 (the comparison stays strictly greater-than)

### Requirement: Price reserve fallbacks
The price reserve SHALL be 0 kWh (target equals the deficit-based floor) with a specific `price_reserve_reason` whenever it cannot be computed, and SHALL report a reason when it is computed, as listed in the scenarios below. Forecast accuracy data is optional: when it is unavailable the reserve SHALL behave exactly as it did without accuracy correction.

#### Scenario: Zero reserve reasons
- **WHEN** the reserve cannot be computed
- **THEN** the reserve SHALL be 0 kWh (target equals the deficit-based floor) with `price_reserve_reason` set as follows
- **AND** `price_forecast.enabled` false → `"disabled"`
- **AND** fewer than 90% of unseen-window slots have a forecast `spot_p50` → `"insufficient_forecast"`
- **AND** the extended load/PV forecast covers fewer than 90% of unseen-window slots → `"insufficient_load_forecast"`
- **AND** the known window has no slots → `"no_known_window"`
- **AND** reading forecasts fails → `"forecast_read_error"` (logged as a warning; the planner run SHALL continue)

#### Scenario: Reasons when the reserve is computed
- **WHEN** the reserve is computed
- **THEN** `price_reserve_reason` SHALL be `"active"` (reserve > 0), `"own_day_cheaper"`, `"below_threshold"` (no slot clears the effective threshold), `"no_net_load"` (no unseen slot has net load) or `"no_charge_capacity"` (the known window cannot charge)

#### Scenario: Forecast store unavailable
- **WHEN** reading the price forecast store raises an error
- **THEN** the planner run SHALL complete with the deficit-based floor as target
- **AND** `price_reserve_reason` SHALL be `"forecast_read_error"`

#### Scenario: Price forecasting disabled
- **GIVEN** `price_forecast.enabled: false`
- **WHEN** the planner runs
- **THEN** no forecast store query SHALL be made and the target SHALL equal the deficit-based floor

#### Scenario: Insufficient or unavailable accuracy data
- **WHEN** fewer than 2 sample days of paired data exist, no rows exist, or reading accuracy data raises an error
- **THEN** for the affected horizons (after the D+1 fallback) bias and typical error SHALL both be 0, prices SHALL NOT be adjusted and the effective threshold SHALL equal the base risk threshold
- **AND** `price_reserve_accuracy_fallback` SHALL be true
- **AND** the planner run SHALL continue and the reserve SHALL equal the value computed before this change

### Requirement: Price reserve debug output
The safety-floor debug output SHALL include the price-reserve keys listed in the scenarios below, and `price_reserve_active` SHALL mean the reserve was sized above 0.

#### Scenario: Debug keys present
- **WHEN** the safety-floor debug output is produced
- **THEN** it SHALL include: `price_reserve_active`, `price_reserve_reason`, `price_reserve_threshold_sek` (base risk threshold), `price_reserve_effective_threshold_sek`, `price_reserve_forecast_bias_sek_kwh` (spot domain), `price_reserve_forecast_error_sek_kwh` (import domain), `price_reserve_accuracy_fallback`, `price_reserve_forecast_accuracy` (per-horizon bias, de-biased MAE and sample days), `price_reserve_corrected_known_slots`, `unseen_window_start`, `unseen_window_end`, `known_cost_sek_kwh` (first marginal value), `own_day_cost_sek_kwh` (first marginal value), `price_reserve_kwh` (sized), `price_reserve_applied_kwh` (target increase over the deficit floor), `forecast_issue_timestamp` (latest issue used) and `final_floor_kwh`

#### Scenario: Active flag semantics and cap key
- **WHEN** the reserve was sized above 0 but the deficit floor already covers it
- **THEN** `price_reserve_active` SHALL still be true and `price_reserve_applied_kwh` SHALL be 0
- **AND** an extra key `price_reserve_capped_by` (`usable_capacity` or `known_window_charge`) SHALL be present only when a physical cap reduced the reserve

#### Scenario: Debug fields present when inactive
- **WHEN** the reserve is 0 for any reason
- **THEN** all debug keys SHALL be present, with `price_reserve_active: false` and the reason set; accuracy keys SHALL carry their fallback values (0, 0, true) when accuracy was not evaluated

#### Scenario: Strategy event is explainable
- **WHEN** a price-reserve strategy event is logged
- **THEN** its details SHALL include the bias, typical error, effective threshold and accuracy-fallback flag
