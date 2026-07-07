# S-Index Price Awareness

## Purpose

TBD

## Requirements

### Requirement: Price floor addon calculation
The system SHALL compute a price-driven floor addon in kWh using a proximity-weighted absolute SEK/kWh spread signal, scaled by battery capacity and risk-level fraction.

#### Scenario: Normal price floor addon — prices rising
- **GIVEN** price forecast data for at least 1 upcoming day is available
- **AND** at least 2 days of historical spot prices exist in `slot_observations`
- **AND** `price_forecast.enabled` is true
- **WHEN** at least one upcoming day's weighted spread is positive
- **THEN** the system SHALL compute, per day offset `d` (1..7): `weighted_spread_d = (avg_spot_p50_d - trailing_14day_avg_spot) × 0.5^((d−1)/2)`
- **AND** SHALL take `weighted_spread_sek = max(weighted_spread_d)` (the day producing the maximum is the driving day)
- **AND** SHALL compute `price_addon_kwh = capacity_kwh × weighted_spread_sek × risk_fraction`
- **AND** `price_addon_kwh` SHALL be positive (floor increases)

#### Scenario: Normal price floor addon — cheap period ahead (asymmetric, no effect on floor)
- **GIVEN** price forecast and historical data are available and `price_forecast.enabled` is true
- **WHEN** every upcoming day's daily average spot p50 is lower than the trailing 14-day average
- **THEN** `weighted_spread_sek` SHALL be negative
- **AND** the *computed* `price_addon_kwh` SHALL be negative (visible in debug for observability)
- **AND** the *effective* change to the safety floor SHALL be zero — the final floor SHALL equal the Layer 1 `safety_floor_kwh` unchanged
- **AND** Kepler's natural slot-level optimization SHALL be relied on to exploit the cheap period via real Nordpool prices (no relaxation of the deficit-based reserve is required)

#### Scenario: No adjustment when prices at average
- **WHEN** every upcoming day's daily average spot equals the trailing average
- **THEN** `price_addon_kwh` SHALL be 0.0 and the final floor SHALL equal the existing safety floor

#### Scenario: Insufficient forecast data
- **WHEN** price forecast data has fewer than 1 upcoming day
- **THEN** the system SHALL return `price_addon_kwh = 0.0` with debug reason `"insufficient_forecast_data"`

#### Scenario: Insufficient historical data
- **WHEN** fewer than 2 days of historical spot prices exist in `slot_observations`
- **OR** `trailing_14day_avg_spot` is None or 0
- **THEN** the system SHALL return `price_addon_kwh = 0.0` with debug reason `"insufficient_historical_data"`

#### Scenario: Price forecast disabled
- **WHEN** `price_forecast.enabled` is false or not present in config
- **THEN** no price data SHALL be fetched
- **AND** the safety floor calculation SHALL behave identically to the pre-Module-3 implementation

---

### Requirement: Proximity-weighted peak price signal
The system SHALL use the **maximum proximity-weighted** daily spread across forecast days D+1 through D+7 as the "upcoming" signal — not an unweighted average or unweighted peak. Each day's spread SHALL be scaled by `weight(d) = 0.5^((d−1) / PRICE_PROXIMITY_HALF_LIFE_DAYS)` with a half-life of 2 days:

| Days ahead | D+1 | D+2 | D+3 | D+4 | D+5 | D+6 | D+7 |
|---|---|---|---|---|---|---|---|
| Weight | 1.00 | 0.71 | 0.50 | 0.35 | 0.25 | 0.18 | 0.13 |

#### Scenario: Single expensive day in an otherwise normal week
- **WHEN** D+1 through D+6 have average spot p50 near the trailing average
- **AND** D+7 has a daily average spot p50 significantly above the trailing average
- **THEN** the driving day SHALL be D+7 and `weighted_spread_sek` SHALL equal D+7's spread × 0.13 (approx)
- **AND** the addon SHALL be positive but heavily damped relative to the same spike at D+1

#### Scenario: Floor ramps up as an expensive day approaches
- **WHEN** an identical price spike is forecast at decreasing distances (e.g. D+6, then D+4, then D+2, then D+1 on successive planning days)
- **THEN** the computed `price_addon_kwh` SHALL strictly increase as the spike gets closer
- **AND** SHALL reach its full unweighted magnitude at D+1

#### Scenario: Near moderate spike outweighs far equal spike
- **WHEN** the same raw spread appears at both D+2 and D+6
- **THEN** the driving day SHALL be D+2 (weight 0.71 > 0.18)

#### Scenario: Uniformly high week
- **WHEN** all days D+1 through D+7 have equally elevated prices
- **THEN** the driving day SHALL be D+1 (highest weight) and the signal SHALL equal D+1's full spread

---

### Requirement: Two-tier safety floor architecture (asymmetric, additive only)
The price addon SHALL be applied *after* the existing `max_safety_buffer_pct` cap (Layer 1), not inside it. The price signal SHALL only be allowed to *raise* the safety floor, never lower it — the deficit-based `safety_floor_kwh` produced by Layer 1 is preserved as a hard lower bound.

#### Scenario: Price addon applied on top of capped base floor
- **GIVEN** the existing safety floor calculation produces `safety_floor_kwh` (already capped at `min_soc + 20% capacity`)
- **WHEN** `price_addon_kwh` is computed
- **THEN** the system SHALL compute `final_floor_kwh = clamp(safety_floor_kwh + price_addon_kwh, min=safety_floor_kwh, max=0.80 × capacity_kwh)`
- **AND** the final floor SHALL be returned in place of the previously-capped floor

#### Scenario: Final floor capped at 80% of battery capacity
- **WHEN** `safety_floor_kwh + price_addon_kwh` exceeds 80% of `capacity_kwh`
- **THEN** `final_floor_kwh` SHALL be clamped to `0.80 × capacity_kwh`

#### Scenario: Final floor never below the deficit-based safety floor
- **WHEN** `price_addon_kwh` is negative (cheap period forecasted)
- **THEN** `final_floor_kwh` SHALL equal `safety_floor_kwh` unchanged
- **AND** the floor SHALL NOT be lowered toward `min_soc_kwh` by the price signal under any circumstance

#### Scenario: No price data — behavior identical to pre-Module-3
- **WHEN** price data is unavailable or `price_forecast.enabled` is false
- **THEN** the function SHALL return `safety_floor_kwh` unchanged (no Layer 2 applied)
- **AND** the result SHALL be byte-for-byte identical to the pre-change implementation

---

### Requirement: Risk-level scaling via RISK_PRICE_KW_FRACTION
The price addon SHALL scale with the user's configured risk appetite using a hardcoded internal table.

#### Scenario: Risk 1 (Safety) — most aggressive price hoarding
- **WHEN** `risk_appetite = 1`
- **THEN** `risk_fraction = 0.15`
- **AND** a 1.0 SEK/kWh positive *weighted* spread SHALL produce `price_addon_kwh = capacity_kwh × 0.15`

#### Scenario: Risk 3 (Neutral) — baseline
- **WHEN** `risk_appetite = 3`
- **THEN** `risk_fraction = 0.10`
- **AND** a 1.0 SEK/kWh positive *weighted* spread SHALL produce `price_addon_kwh = capacity_kwh × 0.10`

#### Scenario: Risk 5 (Gambler) — minimal price hoarding
- **WHEN** `risk_appetite = 5`
- **THEN** `risk_fraction = 0.02`
- **AND** a 5.0 SEK/kWh positive *weighted* spread SHALL produce `price_addon_kwh = capacity_kwh × 0.10`

#### Scenario: Full risk fraction table
The following fractions SHALL be used:

| risk_appetite | risk_fraction |
|---|---|
| 1 | 0.15 |
| 2 | 0.12 |
| 3 | 0.10 |
| 4 | 0.05 |
| 5 | 0.02 |

---

### Requirement: Price floor addon debug output
The system SHALL include price floor addon data in the debug dict returned by `calculate_safety_floor()`.

#### Scenario: Debug data when price adjustment is active
- **WHEN** `price_addon_kwh` is computed (regardless of sign)
- **THEN** the debug output SHALL include:
  - `price_adjustment_active: true`
  - `price_spread_sek` (the proximity-weighted spread used in the formula, float)
  - `raw_spread_sek` (the driving day's unweighted spread, float)
  - `driving_day_offset` (days-ahead of the day that produced the max weighted spread, int)
  - `proximity_weight` (the weight applied to the driving day, float)
  - `peak_upcoming_spot_sek` (the driving day's daily avg spot p50, float)
  - `trailing_avg_spot_sek` (14-day trailing avg, float)
  - `price_addon_kwh` (computed addon before clamp — may be negative, float)
  - `price_addon_applied_kwh` (effective floor change after the asymmetric clamp — always ≥ 0, float)
  - `price_reserve_fraction` (the risk_fraction used, float)
  - `final_floor_kwh` (after price addon + clamp, float)

#### Scenario: Debug data when price adjustment is inactive
- **WHEN** price forecasting is disabled or data is unavailable
- **THEN** the debug output SHALL include `price_adjustment_active: false`
- **AND** SHALL include `price_adjustment_reason` with the specific reason string

---

### Requirement: Strategy event logging for significant price-driven floor increases
The system SHALL log a strategy event via `append_strategy_event()` when the price signal raises the safety floor by 0.5 kWh or more. Negative addons (cheap period ahead) do not change the floor and SHALL NOT produce a strategy event.

#### Scenario: Significant price-driven floor increase
- **WHEN** `price_addon_kwh >= 0.5 kWh`
- **THEN** the system SHALL log a strategy event with type `"STRATEGY_CHANGE"`
- **AND** the event message SHALL indicate prices are above average and the floor has been raised
- **AND** the event data SHALL include `price_spread_sek`, `price_addon_kwh`, and `peak_upcoming_spot_sek`

#### Scenario: No event logged for cheap-period signal
- **WHEN** `price_addon_kwh < 0` (any negative value)
- **THEN** no strategy event SHALL be logged
- **AND** the (negative) `price_addon_kwh` value SHALL still be recorded in debug output for observability

#### Scenario: Trivial price adjustment
- **WHEN** `0 <= price_addon_kwh < 0.5 kWh`
- **THEN** no strategy event SHALL be logged for the price adjustment

---

### Requirement: Pipeline integration for price forecast data
The planner pipeline SHALL fetch price forecast data and pass it to the safety floor calculation when `price_forecast.enabled` is true.

#### Scenario: Pipeline passes price data to safety floor
- **WHEN** the planner pipeline runs in "full" mode
- **AND** `price_forecast.enabled` is true
- **THEN** the pipeline SHALL retrieve daily average spot p50 for D+1 through D+7 from the `price_forecasts` table, keyed by days-ahead offset (int, computed from local calendar dates)
- **AND** SHALL retrieve the trailing 14-day average export price from `slot_observations`
- **AND** SHALL pass both to `calculate_safety_floor()` as `upcoming_daily_avg_spots` and `trailing_avg_spot` (risk appetite is parsed internally from `s_index_cfg` — no extra argument)

#### Scenario: Pipeline skips price data when disabled
- **WHEN** `price_forecast.enabled` is false or absent
- **THEN** the pipeline SHALL NOT fetch any price forecast data
- **AND** SHALL call `calculate_safety_floor()` without price parameters (backward-compatible signature)
