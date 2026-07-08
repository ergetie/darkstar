## ADDED Requirements

### Requirement: MultiDayPlanner computes daily energy quotas from price forecasts
The `MultiDayPlanner` SHALL accept an energy requirement (kWh), a deadline (datetime), and a list of daily average spot prices (one per remaining day). It SHALL return a daily quota allocation (dict of date → kWh) that distributes the energy across days, biased toward cheaper days using inverse-price weighting.

#### Scenario: 3 days remaining with varying prices
- **WHEN** `remaining_kwh=60`, deadline is 3 days away, and daily average prices are [1.5, 0.5, 1.0] SEK/kWh
- **THEN** the planner SHALL allocate more kWh to day 2 (cheapest) and less to day 1 (most expensive)
- **AND** the sum of all daily quotas SHALL equal 60 kWh

#### Scenario: Single day remaining
- **WHEN** `remaining_kwh=40` and deadline is today
- **THEN** the planner SHALL allocate all 40 kWh to today
- **AND** no deferral logic SHALL apply

#### Scenario: Zero remaining energy
- **WHEN** `remaining_kwh=0` (or negative, due to overshoot)
- **THEN** the planner SHALL return zero quota for all remaining days

### Requirement: Minimum daily fraction prevents over-deferral
The `MultiDayPlanner` SHALL enforce a minimum daily fraction on every day except the last day. Each non-final day SHALL receive at least `min_daily_fraction` (configurable, default 10%) of the remaining energy, even if that day is the most expensive.

#### Scenario: Very cheap final day with expensive preceding days
- **WHEN** day 1 price is 3.0 SEK/kWh, day 2 price is 3.0 SEK/kWh, day 3 price is 0.1 SEK/kWh, and `remaining_kwh=60`
- **THEN** day 1 and day 2 SHALL each receive at least 6 kWh (10% of 60)
- **AND** the algorithm SHALL not defer everything to day 3

#### Scenario: All days equally priced
- **WHEN** all remaining days have the same average price
- **THEN** the planner SHALL distribute energy approximately equally across all days

### Requirement: Daily quota respects charger power capacity
The `MultiDayPlanner` SHALL cap each day's quota at `max_power_kw * available_hours * slot_duration_hours` for that day. For the current day, available hours SHALL be calculated from now until end of day (or deadline, whichever is sooner). For future days, available hours SHALL be 24 hours (or hours until deadline on the final day).

#### Scenario: Small charger cannot deliver full quota in one day
- **WHEN** the inverse-price weighting assigns 50 kWh to a day, but the charger's `max_power_kw=3.6` allows only 86.4 kWh/day maximum
- **THEN** the quota for that day SHALL be capped at 86.4 kWh
- **AND** excess energy SHALL be redistributed to other days

#### Scenario: Partial current day
- **WHEN** it is 18:00 and the charger has 6 available hours today at 11 kW
- **THEN** today's maximum possible quota SHALL be 66 kWh (11 * 6)
- **AND** the planner SHALL not assign more than 66 kWh to today

### Requirement: MultiDayPlanner is load-type agnostic
The `MultiDayPlanner` SHALL NOT contain any EV-specific logic. Its interface SHALL accept only: `remaining_kwh` (float), `deadline` (datetime), `daily_prices` (list of float), `max_daily_kwh` (list of float), and `min_daily_fraction` (float, optional). It SHALL return a dict mapping date to quota kWh.

#### Scenario: Non-EV hypothetical consumer
- **WHEN** a pool heater controller calls `MultiDayPlanner` with `remaining_kwh=100`, a deadline 5 days away, and daily prices
- **THEN** the planner SHALL return valid daily quotas without requiring any EV-specific parameters

### Requirement: MultiDayPlanner handles missing or partial price forecasts gracefully
When price forecast data is unavailable for some future days (e.g., the forecast model has not accumulated enough data), the `MultiDayPlanner` SHALL fall back to equal distribution across days with missing prices.

#### Scenario: Forecast available for 3 of 5 remaining days
- **WHEN** price data exists for days 1-3 but not days 4-5
- **THEN** days 4-5 SHALL be assigned the average price of days 1-3
- **AND** the planner SHALL still produce a valid allocation across all 5 days

#### Scenario: No price forecast available at all
- **WHEN** `price_forecast.enabled` is true but no forecast data exists (cold start)
- **THEN** the planner SHALL distribute energy equally across all remaining days
