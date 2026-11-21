## ADDED Requirements

### Requirement: Forecast days contain one slot per local 15-minute slot
Price forecast generation SHALL produce, for each forecast day, exactly the 15-minute slots that start on that local date: 96 on a normal day, 92 on the spring-forward day and 100 on the fall-back day. The last slot of a day SHALL start at 23:45 local time. The next day's 00:00 slot SHALL NOT be generated or stored as part of the previous day.

#### Scenario: Normal day
- **WHEN** a forecast is generated for a normal local date
- **THEN** it contains 96 slots and the last slot starts at 23:45 local time

#### Scenario: DST days
- **WHEN** a forecast is generated for 2026-03-29 or 2026-10-25 in Europe/Stockholm
- **THEN** it contains 92 or 100 slots respectively, and the last slot starts at 23:45 local time

#### Scenario: No duplicate slots across horizons
- **WHEN** a forecast run is persisted for several days ahead
- **THEN** no `slot_start` appears under more than one `days_ahead` value in that run

### Requirement: D+1 forecast fallback is selected by target date and latest issue
The D+1 forecast fallback used before tomorrow's prices are published SHALL return, for every slot whose local start date is tomorrow, one record from the latest forecast issue that covers that slot, regardless of the `days_ahead` it was stored under. Only records with a valid `spot_p50` SHALL be returned, one per slot start, and slots of any other date SHALL NOT be returned.

#### Scenario: Before the daily issue
- **WHEN** only yesterday's issue exists, so tomorrow's slots are stored with `days_ahead` 2, and tomorrow's prices are not yet published
- **THEN** the fallback returns all of tomorrow's slots including 00:00, each with `forecast_days_ahead` 2

#### Scenario: After the daily issue
- **WHEN** today's issue has stored tomorrow's slots with `days_ahead` 1
- **THEN** the fallback returns the new issue's rows with `forecast_days_ahead` 1

#### Scenario: Mixed issues
- **WHEN** some of tomorrow's slots exist in two issues
- **THEN** each slot is taken from its latest issue

#### Scenario: Old overlapping rows
- **WHEN** the database holds rows from an earlier version in which tomorrow's 00:00 is stored under two `days_ahead` values
- **THEN** the fallback contains tomorrow's 00:00 slot exactly once

#### Scenario: Fall-back day
- **WHEN** tomorrow is the fall-back DST day and 100 slots are stored
- **THEN** the fallback contains all 100 slots of that day

#### Scenario: Merged price series is continuous
- **WHEN** published prices end at 23:45 today and the fallback fills tomorrow
- **THEN** the merged price series has no gap at midnight and consecutive slots are 15 minutes apart

### Requirement: Fallback slots carry their source horizon to the planner
Each fallback record SHALL carry the `days_ahead` of its source issue as `forecast_days_ahead`, and the planner price data SHALL keep `price_source` `forecast` and that `forecast_days_ahead` for these slots.

#### Scenario: Source and horizon reach the planner
- **WHEN** fallback slots are merged into the price data
- **THEN** those slots have `price_source` `forecast` and `forecast_days_ahead` in the planner input, and published slots do not carry `forecast_days_ahead`
