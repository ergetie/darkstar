## ADDED Requirements

### Requirement: Cold-start uses pure baseline
A home with insufficient personal data SHALL use the open-meteo baseline alone (no ML nudge), so a new or under-trained home can never receive a wildly wrong forecast.

#### Scenario: Brand-new home
- **WHEN** a home has zero days of its own paired (forecast, actual) data
- **THEN** the final PV forecast SHALL equal the open-meteo baseline (clamped to the physical ceiling)
- **AND** no ML residual SHALL be applied

#### Scenario: Below the ramp threshold
- **WHEN** a home has some but fewer than the configured minimum days of data
- **THEN** the ML residual SHALL be scaled toward zero according to the ramp
- **AND** the baseline SHALL dominate the forecast

### Requirement: Gradual personalization ramp
The ML nudge SHALL be weighted by how many days of the user's own data exist, ramping from 0 (baseline only) to a full (bounded) nudge over a configured window. The same ramp SHALL apply to new and existing users.

#### Scenario: Ramp increases with data
- **WHEN** the number of days of paired data increases over time
- **THEN** the applied fraction of the ML residual SHALL increase monotonically toward the full bounded value
- **AND** SHALL reach full weight only at or beyond the configured ramp window

#### Scenario: Ramp never exceeds the bound
- **WHEN** the ramp reaches full weight
- **THEN** the applied residual SHALL still be limited by the configured bound (fraction of baseline)
- **AND** the final forecast SHALL still be capped at the physical ceiling

#### Scenario: Aurora PV forecasting disabled bypasses ramp
- **WHEN** `forecasting.aurora_pv_enabled` is false
- **THEN** the personalization ramp SHALL NOT apply an ML residual regardless of paired day count
- **AND** the final PV forecast SHALL use the Open-Meteo baseline clamped to the physical ceiling

### Requirement: Existing-user backfill
On adoption, the system SHALL attempt a backfill of missing Open-Meteo baseline slots for up to the configured number of days (default ~28, matching the `past_days` 15-min ceiling) by pairing stored actual production with open-meteo historical forecasts, so existing users gain personalization quickly without discarding production history. The backfill SHALL auto-limit to slots that have actual production but do not already have a stored Open-Meteo baseline.

#### Scenario: Backfill seeds personalization for an existing user
- **WHEN** the change is adopted on a system with existing production history
- **THEN** the system SHALL identify recent actual-production slots missing a stored Open-Meteo baseline
- **AND** fetch open-meteo historical forecasts only when missing baseline slots exist
- **AND** store baseline values only for those missing slots to seed residual training and the ramp's day-count

#### Scenario: New install has no history to backfill
- **WHEN** the change is adopted on a system with little or no production history (e.g. a new install)
- **THEN** the effective backfill SHALL shrink to zero
- **AND** the system SHALL run on the open-meteo baseline and ramp forward as the user accumulates data
- **AND** no error SHALL be raised for the empty backfill

#### Scenario: Backfill unavailable
- **WHEN** open-meteo historical forecasts cannot be retrieved for the backfill window
- **THEN** the system SHALL proceed with baseline-only and accumulate data from the current time
- **AND** log that backfill was skipped

#### Scenario: Production history preserved
- **WHEN** the change is adopted
- **THEN** existing `slot_observations` actual-production data SHALL be retained unchanged

### Requirement: Physical safety ceiling
The final PV forecast SHALL never exceed a physically plausible ceiling, regardless of baseline or ML output.

#### Scenario: Ceiling caps the forecast
- **WHEN** the composed forecast for a slot would exceed `kWp · slot_hours · max_efficiency` (with the inverter AC limit applied)
- **THEN** the system SHALL clamp the final value to that ceiling
- **AND** the clamp SHALL apply in all modes (baseline-only and personalized)
