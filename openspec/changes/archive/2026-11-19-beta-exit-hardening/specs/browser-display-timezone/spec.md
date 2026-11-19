# Spec Delta

## Purpose
Show times in the viewer's browser timezone while keeping backend-defined buckets and tariff windows in the configured plan timezone.

## ADDED Requirements

### Requirement: Display in browser timezone
All clock labels, tooltips and axis labels SHALL use the browser timezone and 24-hour clocks, with no hardcoded timezone or locale.

#### Scenario: Browser in Auckland
- **WHEN** the browser timezone is Pacific/Auckland and a slot starts at 08:00+02:00 Stockholm
- **THEN** its label shows the Auckland wall-clock time

### Requirement: Plan timezone kept for backend semantics
Transfer-fee rule matching and cost-series bucket boundaries SHALL use `config.timezone` or `time_axis.timezone`; when `config.timezone` is empty the browser timezone SHALL be the fallback.

#### Scenario: Rule matching
- **WHEN** browser and config timezones differ
- **THEN** the fee for a slot uses the config-timezone hour

### Requirement: Consistent day grouping
Today and tomorrow grouping on the dashboard chart SHALL use the browser day and SHALL neither drop nor duplicate a slot across the history and forecast seam.

#### Scenario: Seam
- **WHEN** the browser timezone differs from the config timezone
- **THEN** every slot in the window appears exactly once

### Requirement: Date keys are locale independent and local
Date keys SHALL be built independently of locale and use local calendar dates, not UTC dates.

#### Scenario: Near midnight
- **WHEN** it is 00:30 local, UTC date being the previous day
- **THEN** "today" filters use the local date
