## REMOVED Requirements

### Requirement: Price floor addon calculation
**Reason**: The daily-average spread signal was measured on production data to be worth ~0 SEK/month and to lose money on ~40% of days; it is replaced by the first-unseen-day price reserve.
**Migration**: None for users. The price-driven part of the target SoC is now computed by "Price reserve for the first unseen day".

### Requirement: Proximity-weighted peak price signal
**Reason**: Replaced; the new rule uses only the first unseen day's cheapest charging hours, not a weighted 7-day spread.
**Migration**: None.

### Requirement: Two-tier safety floor architecture (asymmetric, additive only)
**Reason**: The additive combination is replaced by a max() combination that cannot double-count energy already reserved by the deficit floor.
**Migration**: See "Combination with the deficit-based safety floor".

### Requirement: Risk-level scaling via RISK_PRICE_KW_FRACTION
**Reason**: Replaced by a risk-dependent profitability threshold.
**Migration**: See "Risk-dependent profitability threshold".

### Requirement: Price floor addon debug output
**Reason**: Replaced by price reserve debug output.
**Migration**: See "Price reserve debug output". The `price_addon_*`, `price_spread_sek`, `raw_spread_sek`, `driving_day_offset`, `proximity_weight`, `peak_upcoming_spot_sek`, `trailing_avg_spot_sek` and `price_reserve_fraction` debug keys are removed.

### Requirement: Strategy event logging for significant price-driven floor increases
**Reason**: Logged on every planner run (event spam); replaced by a deduplicated event.
**Migration**: See "Deduplicated price reserve strategy event".

### Requirement: Pipeline integration for price forecast data
**Reason**: The daily-average and trailing-average inputs are no longer used.
**Migration**: See "Pipeline integration of the price reserve".

## ADDED Requirements

### Requirement: Price reserve for the first unseen day
On every planner run in `full` mode with `price_forecast.enabled: true`, the system SHALL compute a price reserve (kWh, battery-side) for the **unseen window**: the 24 hours immediately after the end of the published-price horizon (the same window the deficit-based safety floor looks at). The reserve SHALL use, for every unseen-window slot, the latest-issue `spot_p50` forecast converted to an import price with the user's own pricing configuration (VAT, energy tax, flat or time-of-use transfer fee for that slot), and, for every **known-window** slot (from the current slot to the end of the published-price horizon), the planner's own import price.

Per delivered kWh, the system SHALL define:
- `known_cost` = marginal known-window import price ÷ (charge_efficiency × discharge_efficiency) + wear cost, taking known-window slots cheapest-first, each slot contributing at most `max_charge_kw × slot_hours × charge_efficiency` stored kWh;
- `own_day_cost` = the same, computed over the unseen-window slots (cheapest-first) using forecast import prices;
- for an unseen-window slot `h` with forecast import price `P_h`: `gain_h = min(P_h, own_day_cost) − known_cost`.

The system SHALL visit unseen-window slots from the highest `P_h` to the lowest and add energy for slot `h` only while `gain_h > threshold` (see "Risk-dependent profitability threshold"), recomputing the marginal `known_cost` and `own_day_cost` as energy is added. The energy added for slot `h` SHALL be `min(net_load_h, max_discharge_kw × slot_hours) / discharge_efficiency`, where `net_load_h = max(0, load_forecast_kwh − pv_forecast_kwh)` from the same extended forecast data the deficit-based floor uses.

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
The price reserve SHALL use only the user's own configuration, with the same resolution the solver uses:
- charge and discharge power limits resolved exactly as the solver adapter does (Ampere control unit: current × battery nominal voltage; Watt control unit: watt limits), through one shared resolver function used by both the adapter and the reserve; the resolver's discharge limit is used as is (the inverter AC limit is intentionally not applied, so reserve and solver never disagree);
- `battery.charge_efficiency` and `battery.discharge_efficiency` with the solver's defaults when unset;
- wear cost from `battery_economics.battery_cycle_cost_kwh` (default 0.0);
- `battery.capacity_kwh`, `battery.min_soc_percent`, `battery.max_soc_percent`;
- the user's `pricing` section for every forecast slot's import price.

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
The profitability threshold (SEK per delivered kWh) SHALL depend on `s_index.risk_appetite`: 1 → 0.20, 2 → 0.15, 3 → 0.10, 4 → 0.05, 5 → 0.00. Unknown values SHALL use the risk-3 threshold.

#### Scenario: Cautious user needs a larger margin
- **GIVEN** `gain_h = 0.12` SEK/kWh for every candidate slot
- **WHEN** risk appetite is 1
- **THEN** the reserve SHALL be 0 kWh
- **AND** with risk appetite 3 the same inputs SHALL produce a positive reserve

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
The price reserve SHALL be 0 kWh (target equals the deficit-based floor) with a specific `price_reserve_reason` when:
- `price_forecast.enabled` is false → `"disabled"`;
- fewer than 90% of unseen-window slots have a forecast `spot_p50` → `"insufficient_forecast"`;
- the extended load/PV forecast covers fewer than 90% of unseen-window slots → `"insufficient_load_forecast"`;
- the known window has no slots → `"no_known_window"`;
- reading forecasts fails → `"forecast_read_error"` (logged as a warning; the planner run SHALL continue).

When the reserve is computed, `price_reserve_reason` SHALL be `"active"` (reserve > 0), `"own_day_cheaper"`, `"below_threshold"` (no slot clears the threshold), `"no_net_load"` (no unseen slot has net load) or `"no_charge_capacity"` (the known window cannot charge).

#### Scenario: Forecast store unavailable
- **WHEN** reading the price forecast store raises an error
- **THEN** the planner run SHALL complete with the deficit-based floor as target
- **AND** `price_reserve_reason` SHALL be `"forecast_read_error"`

#### Scenario: Price forecasting disabled
- **GIVEN** `price_forecast.enabled: false`
- **WHEN** the planner runs
- **THEN** no forecast store query SHALL be made and the target SHALL equal the deficit-based floor

### Requirement: Price reserve debug output
The safety-floor debug output SHALL include: `price_reserve_active`, `price_reserve_reason`, `price_reserve_threshold_sek`, `unseen_window_start`, `unseen_window_end`, `known_cost_sek_kwh` (first marginal value), `own_day_cost_sek_kwh` (first marginal value), `price_reserve_kwh` (sized), `price_reserve_applied_kwh` (target increase over the deficit floor), `forecast_issue_timestamp` (latest issue used) and `final_floor_kwh`. `price_reserve_active` SHALL mean the reserve was sized above 0, even when the deficit floor already covers it (`price_reserve_applied_kwh` is then 0). An extra key `price_reserve_capped_by` (`usable_capacity` or `known_window_charge`) SHALL be present only when a physical cap reduced the reserve.

#### Scenario: Debug fields present when inactive
- **WHEN** the reserve is 0 for any reason
- **THEN** all debug keys SHALL be present, with `price_reserve_active: false` and the reason set

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
