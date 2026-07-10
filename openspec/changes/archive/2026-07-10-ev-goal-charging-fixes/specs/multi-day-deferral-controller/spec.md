## MODIFIED Requirements

### Requirement: MultiDayPlanner computes daily energy quotas from price forecasts
The `MultiDayPlanner` SHALL accept an energy requirement (kWh), a deadline (datetime), and a list of daily average spot prices (one per remaining day, **including day 0 = today**). It SHALL return a daily quota allocation (dict of date → kWh) that distributes the energy across days, biased toward cheaper days using inverse-price weighting. The caller (pipeline) SHALL supply today's price computed from today's **remaining** slots (`slot_start >= now`), so today competes on its real price rather than a fallback average.

#### Scenario: 3 days remaining with varying prices
- **WHEN** `remaining_kwh=60`, deadline is 3 days away, and daily average prices are [1.5, 0.5, 1.0] SEK/kWh
- **THEN** the planner SHALL allocate more kWh to day 2 (cheapest) and less to day 1 (most expensive)
- **AND** the sum of all daily quotas SHALL equal 60 kWh

#### Scenario: Today is the cheapest day
- **WHEN** today's remaining-slot average price is lower than every forecast day
- **THEN** today's quota SHALL be the largest allocation (subject to capacity caps)
- **AND** today's price SHALL NOT be substituted with the future-day average

#### Scenario: Single day remaining
- **WHEN** `remaining_kwh=40` and deadline is today
- **THEN** the planner SHALL allocate all 40 kWh to today
- **AND** no deferral logic SHALL apply

#### Scenario: Zero remaining energy
- **WHEN** `remaining_kwh=0` (or negative, due to overshoot)
- **THEN** the planner SHALL return zero quota for all remaining days

### Requirement: Daily quota respects charger power capacity
The `MultiDayPlanner` SHALL cap each day's quota at `max_power_kw * available_hours * slot_duration_hours` for that day. For the current day, available hours SHALL be calculated from now until end of day (or deadline, whichever is sooner). For future days, available hours SHALL be 24 hours (or hours until deadline on the final day). Every returned allocation SHALL be within `[0, that day's cap]` after all redistribution and rescaling steps — floor-redistribution SHALL never drive an allocation negative, and rescaling SHALL never push a capped day above its cap.

#### Scenario: Small charger cannot deliver full quota in one day
- **WHEN** the inverse-price weighting assigns 50 kWh to a day, but the charger's `max_power_kw=3.6` allows only 86.4 kWh/day maximum
- **THEN** the quota for that day SHALL be capped at 86.4 kWh
- **AND** excess energy SHALL be redistributed to other days

#### Scenario: Partial current day
- **WHEN** it is 18:00 and the charger has 6 available hours today at 11 kW
- **THEN** today's maximum possible quota SHALL be 66 kWh (11 * 6)
- **AND** the planner SHALL not assign more than 66 kWh to today

#### Scenario: Extreme floor redistribution stays physical
- **WHEN** the minimum-daily-fraction floors exceed what later days can absorb
- **THEN** no day's allocation SHALL be negative and no day SHALL exceed its capacity cap
- **AND** the sum of allocations SHALL NOT exceed `remaining_kwh`
