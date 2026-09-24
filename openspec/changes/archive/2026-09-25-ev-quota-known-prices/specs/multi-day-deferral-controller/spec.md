## MODIFIED Requirements

### Requirement: MultiDayPlanner computes daily energy quotas from price forecasts
The `MultiDayPlanner` SHALL accept an energy requirement (kWh), a deadline (datetime), and a list of daily average spot prices (one per remaining day, **including day 0 = today**). It SHALL return a daily quota allocation (dict of date → kWh) that distributes the energy across days, biased toward cheaper days using inverse-price weighting. The caller (pipeline) SHALL supply today's price computed from today's **remaining** slots (`slot_start >= now`), so today competes on its real price rather than a fallback average. Each day's average SHALL be computed per slot from the known-price resolver: the published Nordpool spot where available, and the forecast `spot_p50` only for slots without a published price.

#### Scenario: 3 days remaining with varying prices
- **WHEN** `remaining_kwh=60`, deadline is 3 days away, and daily average prices are [1.5, 0.5, 1.0] SEK/kWh
- **THEN** the planner SHALL allocate more kWh to day 2 (cheapest) and less to day 1 (most expensive)
- **AND** the sum of all daily quotas SHALL equal 60 kWh

#### Scenario: Today is the cheapest day
- **WHEN** today's remaining-slot average price is lower than every forecast day
- **THEN** today's quota SHALL be the largest allocation (subject to capacity caps)
- **AND** today's price SHALL NOT be substituted with the future-day average

#### Scenario: Stale cheap forecast for today, expensive published price
- **WHEN** today's remaining slots have published spot ≈2.0 SEK/kWh, the stale forecast for those slots is ≈0.2 SEK/kWh, and the later days before the deadline have forecast averages of 0.6–1.2 SEK/kWh
- **THEN** today's average SHALL be computed from the published ≈2.0 SEK/kWh
- **AND** today's quota SHALL NOT be the largest allocation

#### Scenario: Tomorrow's prices published
- **WHEN** D+1 Nordpool prices are published (after the day-ahead auction)
- **THEN** D+1's average SHALL use the published prices, not the forecast

#### Scenario: Single day remaining
- **WHEN** `remaining_kwh=40` and deadline is today
- **THEN** the planner SHALL allocate all 40 kWh to today
- **AND** no deferral logic SHALL apply

#### Scenario: Zero remaining energy
- **WHEN** `remaining_kwh=0` (or negative, due to overshoot)
- **THEN** the planner SHALL return zero quota for all remaining days
