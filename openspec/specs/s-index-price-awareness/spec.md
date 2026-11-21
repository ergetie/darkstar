# S-Index Price Awareness

## Purpose

Store cheap energy for the first day the planner cannot see prices for, by raising the end-of-horizon SoC target (price reserve) when forecast prices show that charging in the cheapest known hours beats buying later, sized from the user's own battery, fee and risk settings and combined with the deficit-based safety floor.

## Requirements

### Requirement: Price reserve for the first unseen day
On every planner run in `full` mode with `price_forecast.enabled: true`, the system SHALL compute a price reserve (kWh, battery-side) for the **unseen window**: the 24 hours immediately after the end of the published-price horizon (the same window the deficit-based safety floor looks at). The reserve SHALL be sized per unseen-window slot as described in the scenarios below.

#### Scenario: Prices used for reserve sizing
- **WHEN** the reserve is computed
- **THEN** the system SHALL use, for every unseen-window slot, the latest-issue `spot_p50` forecast converted to an import price with the user's own pricing configuration (VAT, energy tax, flat or time-of-use transfer fee for that slot)
- **AND** for every **known-window** slot (from the current slot to the end of the published-price horizon), the planner's own import price

#### Scenario: Cost and gain definitions
- **WHEN** the reserve is sized
- **THEN** per delivered kWh the system SHALL define `known_cost` = marginal known-window import price ÷ (charge_efficiency × discharge_efficiency) + wear cost, taking known-window slots cheapest-first, each slot contributing at most `max_charge_kw × slot_hours × charge_efficiency` stored kWh
- **AND** `own_day_cost` = the same, computed over the unseen-window slots (cheapest-first) using forecast import prices
- **AND** for an unseen-window slot `h` with forecast import price `P_h`: `gain_h = min(P_h, own_day_cost) - known_cost`

#### Scenario: Slot visiting and energy added
- **WHEN** the reserve is sized
- **THEN** the system SHALL visit unseen-window slots from the highest `P_h` to the lowest and add energy for slot `h` only while `gain_h > threshold` (see "Risk-dependent profitability threshold"), recomputing the marginal `known_cost` and `own_day_cost` as energy is added
- **AND** the energy added for slot `h` SHALL be `min(net_load_h, max_discharge_kw × slot_hours) / discharge_efficiency`, where `net_load_h = max(0, load_forecast_kwh - pv_forecast_kwh)` from the same extended forecast data the deficit-based floor uses

#### Scenario: Unseen day is more expensive to charge than the known window
- **GIVEN** the known window's cheapest charging slots cost 0.80 SEK/kWh import and the unseen day's cheapest forecast slots cost 1.40 SEK/kWh
- **AND** the unseen day has expensive evening slots (2.50 SEK/kWh) with 6 kWh net load
- **WHEN** the planner runs with risk appetite 3
- **THEN** the price reserve SHALL include the energy needed to cover those 6 kWh (divided by discharge efficiency)
- **AND** the debug output SHALL report `price_reserve_active: true`

#### Scenario: Unseen day can charge cheaply on its own
- **GIVEN** the unseen day's own cheapest forecast slots are cheaper than the known window's cheapest slots
- **WHEN** the planner runs
- **THEN** the price reserve SHALL be 0 kWh
- **AND** `price_reserve_reason` SHALL be `"own_day_cheaper"`

#### Scenario: Expensive hour without household load adds nothing
- **GIVEN** an unseen-window slot with a high forecast price but `net_load_h = 0` (PV covers load)
- **WHEN** the reserve is sized
- **THEN** that slot SHALL contribute 0 kWh

#### Scenario: Before tomorrow's prices are published
- **GIVEN** it is 10:00 and only today's prices are published
- **WHEN** the planner runs
- **THEN** the unseen window SHALL be tomorrow (the 24 hours after today's last published slot) and the reserve SHALL be computed for it in the same way

### Requirement: Per-user battery and price parameters
The price reserve SHALL use only the user's own configuration, with the same resolution the solver uses, as listed in the scenarios below.

#### Scenario: Parameters resolved from user configuration
- **WHEN** the price reserve is computed
- **THEN** charge and discharge power limits SHALL be resolved exactly as the solver adapter does (Ampere control unit: current × battery nominal voltage; Watt control unit: watt limits), through one shared resolver function used by both the adapter and the reserve
- **AND** the resolver's discharge limit SHALL be used as is (the inverter AC limit is intentionally not applied, so reserve and solver never disagree)
- **AND** `battery.charge_efficiency` and `battery.discharge_efficiency` SHALL be used with the solver's defaults when unset
- **AND** wear cost SHALL come from `battery_economics.battery_cycle_cost_kwh` (default 0.0)
- **AND** `battery.capacity_kwh`, `battery.min_soc_percent` and `battery.max_soc_percent` SHALL be used
- **AND** the user's `pricing` section SHALL be used for every forecast slot's import price

#### Scenario: Ampere-controlled inverter
- **GIVEN** `executor.inverter.control_unit: "A"`, `max_charge_a: 185`, `nominal_voltage_v: 48`
- **WHEN** the reserve is sized
- **THEN** the charge limit used SHALL be 8.88 kW, identical to the solver's limit

#### Scenario: Time-of-use transfer fees
- **GIVEN** `pricing.transfer_fee_mode: time_of_use` with a higher fee on weekdays 06-22
- **WHEN** unseen-window forecast slots are priced
- **THEN** each slot's import price SHALL include the transfer fee that applies to that slot

#### Scenario: Shared power-limit resolver
- **WHEN** the solver adapter and the price reserve resolve battery power limits from the same configuration
- **THEN** both SHALL obtain identical values from the same function

### Requirement: Risk-dependent profitability threshold
The base profitability threshold (SEK per delivered kWh) SHALL depend on `s_index.risk_appetite`: 1 → 0.20, 2 → 0.15, 3 → 0.10, 4 → 0.05, 5 → 0.00; unknown values SHALL use the risk-3 threshold. The **effective** activation threshold SHALL be `max(base threshold, typical forecast error × (1 + VAT))`, where typical forecast error is the largest 7-day de-biased MAE (shared accuracy function) among the horizons of the forecast-sourced slots in use, or 0 when accuracy data is unavailable.

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

### Requirement: Physical limits of the reserve
The price reserve SHALL NOT exceed:
- usable capacity `(max_soc_percent − min_soc_percent) × capacity_kwh`;
- the energy that can be added in the known window: `max(0, max_charge_kw × known_window_hours × charge_efficiency)` above the current SoC, so the target is reachable without violating the solver's power limits.

#### Scenario: Short known window
- **GIVEN** only 2 hours of known slots remain and the charge limit is 5 kW with charge efficiency 0.9
- **WHEN** the sized reserve would be 15 kWh above the current SoC
- **THEN** the applied reserve SHALL be capped so that the target SoC is at most current SoC + 9 kWh

### Requirement: Combination with the deficit-based safety floor
The final end-of-horizon SoC target SHALL be `max(safety_floor_kwh, min_soc_kwh + price_reserve_kwh)`, clamped to `[min_soc_kwh, max_soc_kwh]`. The price reserve SHALL never lower the deficit-based floor and SHALL never be added on top of it.

#### Scenario: Deficit floor already covers the reserve
- **GIVEN** `safety_floor_kwh = 10.3`, `min_soc_kwh = 4.05` and `price_reserve_kwh = 5.0`
- **WHEN** the target is computed
- **THEN** the target SHALL be 10.3 kWh

#### Scenario: Reserve exceeds the deficit floor
- **GIVEN** `safety_floor_kwh = 10.3`, `min_soc_kwh = 4.05` and `price_reserve_kwh = 12.0`
- **WHEN** the target is computed
- **THEN** the target SHALL be 16.05 kWh

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

### Requirement: Deduplicated price reserve strategy event
The planner pipeline SHALL append a `STRATEGY_CHANGE` event, tagged `details.kind = "price_reserve"` (the tag identifies the most recent price-reserve event), describing the price reserve only when `price_reserve_applied_kwh` differs by at least 1.0 kWh from the value in the most recent price-reserve event, or when the reserve switches between active and inactive. Event logging failures SHALL be logged as warnings and SHALL NOT fail the planner run.

#### Scenario: Unchanged reserve across runs
- **GIVEN** the previous price-reserve event recorded 6.0 kWh
- **WHEN** a new run applies 6.4 kWh
- **THEN** no new event SHALL be appended

### Requirement: Pipeline integration of the price reserve
The planner pipeline SHALL, in `full` mode, fetch unseen-window forecast spot prices (latest issue per slot, `spot_p50` not null) off the event loop, pass them together with the known-window prices and the extended forecast data to the safety-floor calculation, and use the returned final floor as the solver's terminal SoC target. The initial SoC SHALL be resolved once, before the safety floor, and shared by the reserve and the solver. In `baseline` mode no reserve SHALL be computed.

#### Scenario: Target reaches the solver
- **WHEN** a full planner run computes a final floor of 16.05 kWh
- **THEN** the solver configuration's `target_soc_kwh` SHALL be 16.05

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
