## Purpose

Display Open-Meteo-derived PV production forecasts alongside Aurora ML forecasts in the Aurora Forecast Horizon chart, enabling users to compare raw weather model output with ML-enhanced predictions.

## Requirements

### Requirement: Open-Meteo PV Forecast Display

The Aurora Forecast Horizon chart SHALL display an Open-Meteo-derived PV production forecast line alongside the Aurora ML forecast, allowing users to compare the raw weather model output with Aurora's ML-enhanced predictions.

#### Scenario: Open-Meteo line visible in PV mode
- **WHEN** user views the Aurora Forecast Horizon chart in PV mode with probabilistic mode enabled
- **THEN** the chart SHALL display a solid amber line labeled "Open-Meteo" showing PV production estimates derived from Open-Meteo radiation data

#### Scenario: Open-Meteo line toggleable via legend
- **WHEN** user clicks the "Open-Meteo" label in the chart legend
- **THEN** the Open-Meteo line SHALL toggle visibility (hide if shown, show if hidden)

### Requirement: Per-Array Forecast Lines

The chart SHALL display individual dashed lines for each configured solar array's Open-Meteo forecast, enabling users to understand per-array contributions.

#### Scenario: Multiple arrays shown as dashed lines
- **WHEN** the system configuration contains multiple solar arrays
- **THEN** the chart SHALL display a dashed line for each array using the array's name as the label

#### Scenario: Single array shows one dashed line
- **WHEN** the system configuration contains a single solar array
- **THEN** the chart SHALL display one dashed line for that array

#### Scenario: Per-array lines toggleable via legend
- **WHEN** user clicks an array name label in the chart legend
- **THEN** that array's dashed line SHALL toggle visibility

### Requirement: Fixed 72-Hour Window

The Forecast Horizon chart SHALL use a fixed time window from 00:00 yesterday to 00:00 the day after tomorrow (72 hours total), anchored to calendar days rather than the current time.

#### Scenario: Window covers three days
- **WHEN** user views the Forecast Horizon chart at any time during a day
- **THEN** the chart SHALL display data from 00:00 yesterday to 00:00 the day after tomorrow (72 hours)

#### Scenario: Window resets at midnight
- **WHEN** the current time crosses midnight
- **THEN** the chart window SHALL shift to show the new "yesterday" through "day after tomorrow"

### Requirement: Historical Actuals Visible

The chart SHALL display historical actual PV production data in the "Actual" line for past time slots within the fixed 72-hour window.

#### Scenario: Actual line shows past production
- **WHEN** historical PV production data exists for past slots within the 72-hour window
- **THEN** the chart SHALL display the "Actual" line with observed PV values for those slots

#### Scenario: Actual line gaps for missing data
- **WHEN** historical PV production data is missing for some past slots
- **THEN** the Actual line SHALL have gaps (null values) for those slots rather than showing zero

### Requirement: Open-Meteo Forecast Data for All Slots

The backend SHALL provide Open-Meteo forecast data for all 72 hours (yesterday, today, and tomorrow) using the forecast API with `past_days=1` and `forecast_days=2`. The fetching mechanism MUST be completely asynchronous to prevent blocking the main event loop during API timeouts or DNS failures.

#### Scenario: Yesterday's slots show hindcast data
- **WHEN** the Aurora dashboard generates forecast slots
- **THEN** yesterday's slots SHALL show Open-Meteo hindcast data (what the model would have predicted)

#### Scenario: Today and tomorrow's slots show forecast data
- **WHEN** the Aurora dashboard generates forecast slots
- **THEN** today and tomorrow's slots SHALL show Open-Meteo forecast data

#### Scenario: Open-Meteo Fetch Timeout
- **WHEN** the Open-Meteo API is unreachable due to network or DNS failure
- **THEN** the asynchronous fetch operation SHALL time out without blocking the main event loop
- **AND** the system SHALL gracefully return an empty dataset for that execution cycle

#### Scenario: Extended forecast days parameter
- **WHEN** a caller requests weather with `forecast_days=16`
- **THEN** the function SHALL fetch 16 days of forecast data from Open-Meteo
- **AND** default callers (no explicit forecast_days) SHALL continue receiving 2-day forecasts

#### Scenario: Additional weather parameters
- **WHEN** a caller requests weather with additional parameters (e.g., `wind_speed_10m`)
- **THEN** the response SHALL include those parameters alongside existing ones (temperature, cloud cover, radiation)
- **AND** default callers (no explicit extra parameters) SHALL receive only the original parameter set

### Requirement: History Series in Horizon Object

The `/aurora/dashboard` API SHALL return historical actuals in `horizon.history_series` with proper structure for the PV and Load tabs.

#### Scenario: Dashboard returns history series in horizon object
- **WHEN** the Aurora dashboard API is called
- **THEN** the response SHALL contain `horizon.history_series` with `pv` and `load` arrays
- **AND** each entry SHALL have `timestamp`, `value`, and optional `confidence`

### Requirement: Open-Meteo PV Calculation
The backend SHALL calculate per-array PV production estimates from Open-Meteo radiation data using physics-based POA (Plane of Array) irradiance calculation that accounts for each array's tilt and azimuth.

#### Scenario: Per-array PV estimate inputs
- **WHEN** per-array PV production is calculated from Open-Meteo radiation
- **THEN** the calculation SHALL use `calculate_physics_pv()` with:
  - `radiation_w_m2` = shortwave radiation from Open-Meteo (W/m²)
  - `solar_arrays` = array configs including `kwp`, `tilt`, and `azimuth`
  - `slot_start` = timestamp for solar position calculation
  - `latitude` / `longitude` = system location

#### Scenario: Azimuth convention conversion
- **WHEN** POA irradiance is calculated for a solar array
- **THEN** the solar azimuth SHALL be converted from North convention (0°=North, clockwise) to South convention (0°=South, positive=West) before calculating POA irradiance

#### Scenario: Per-array curves reflect panel orientation

- **WHEN** the system has multiple solar arrays with different tilt/azimuth values
- **THEN** the Open-Meteo per-array lines SHALL show different curve shapes reflecting each array's orientation relative to the sun's path

#### Scenario: PV calculated using physics model

- **WHEN** Open-Meteo radiation data is available for a time slot
- **THEN** the system SHALL calculate PV estimates using POA irradiance with tilt, azimuth, and solar position

#### Scenario: Per-array capacity used for individual lines

- **WHEN** calculating per-array PV estimates
- **THEN** the system SHALL use that array's `kwp`, `tilt`, and `azimuth` values

#### Scenario: Null returned for missing radiation data

- **WHEN** Open-Meteo radiation data is unavailable for a time slot
- **THEN** the system SHALL return null for that slot's Open-Meteo PV estimate

#### Scenario: Azimuth convention correctly converted

- **WHEN** calculating POA irradiance for a south-facing panel at solar noon
- **THEN** the angle-of-incidence SHALL be near zero (direct beam aligned with panel normal)
- **AND** the PV estimate SHALL be approximately `(radiation/1000) × kwp × efficiency × 0.25h`

### Requirement: Efficient Live PV Slot Mapping

The live Open-Meteo forecast path SHALL map PV power to each requested slot by direct lookup on a canonical UTC instant key, so that mapping cost does not grow with the length of the fetched solar series. Both series keys and slot start times SHALL be normalized to the same canonical form (the 15-minute-floored UTC instant) before matching, so the match MUST be independent of datetime type (python `datetime`, pytz-aware, or pandas `Timestamp`), timezone representation, and DST `fold`.

#### Scenario: Slot matches a series timestamp in a different timezone
- **WHEN** a slot start is a pytz-aware or pandas Timestamp local time and the series key for the same instant is a fixed-offset aware datetime
- **THEN** the slot SHALL receive that key's summed watts converted to kWh (`watts * 0.25 / 1000`)

#### Scenario: Repeated autumn DST hour matches
- **WHEN** slots come from `dst_safe_date_range` in Europe/Stockholm covering the repeated hour (e.g. 2026-10-25 02:00–02:45 +01:00, fold=1) and the series has fixed-offset keys for those instants
- **THEN** every slot SHALL be matched, no slot SHALL be reported as estimated, the incomplete-forecast error SHALL NOT be recorded, and forecast errors SHALL be cleared

#### Scenario: Spring-forward gap matches
- **WHEN** slots span the spring-forward transition (e.g. 2026-03-29 in Europe/Stockholm) and the series covers every instant
- **THEN** every slot SHALL be matched and no slot SHALL be reported as estimated

#### Scenario: Slot has no matching series timestamp
- **WHEN** no series key equals the slot's canonical instant
- **THEN** the slot SHALL be filled from the stored-forecast fallback and counted as estimated, never defaulted to zero

#### Scenario: Long series does not slow mapping
- **WHEN** the fetched series contains thousands of historical entries before the first requested slot
- **THEN** mapping a 7-day (672-slot) request SHALL complete in well under one second and produce the same values as with only the relevant entries

### Requirement: Live PV Fetch Requests Minimal History

The live Open-Meteo PV fetch in `_get_forecast_data_async` SHALL request `past_days=1` for every configured solar array instead of relying on the library default.

#### Scenario: Each array requests one past day
- **WHEN** the live forecast is fetched for one or more solar arrays
- **THEN** every `OpenMeteoSolarForecast` instance SHALL be constructed with `past_days=1`

#### Scenario: Slots from today remain covered
- **WHEN** requested slots start at or after 00:00 today in the configured timezone
- **THEN** every slot within the forecast horizon SHALL receive Open-Meteo PV data

### Requirement: Partial stored-forecast fallback
When the Open-Meteo request fails, the system SHALL build the PV forecast from stored Open-Meteo baselines for every price slot that has one, and SHALL fill each remaining slot with the stored value of the most recent same local time-of-day. Missing slots SHALL never default to zero.

#### Scenario: Full coverage
- **WHEN** the API fails and every price slot has a stored value
- **THEN** the stored values are used and zero slots are reported as estimated

#### Scenario: Partial coverage
- **WHEN** the API fails and stored data ends before the horizon
- **THEN** stored slots keep their values, missing slots take the latest same-time-of-day stored value, and the number of filled slots is reported

#### Scenario: Never silent zero
- **WHEN** any slot cannot be filled from stored data or a same-time-of-day profile
- **THEN** it is not set to zero silently and the whole fallback fails (all-or-nothing: partial forecasts with unfillable slots are not used)

### Requirement: Same-time-of-day lookup window
The same-time-of-day lookup SHALL use stored baselines from 14 days before the first price slot through the horizon end, taking the latest stored day before the slot, else the earliest after it.

#### Scenario: Gap in the middle
- **WHEN** a slot has no stored value but the same time of day is stored on an earlier and a later day
- **THEN** the earlier day's value is used

### Requirement: Empty or incomplete API responses are not zero
An empty successful Open-Meteo response SHALL be treated as a failure, and slots absent from a successful response SHALL be filled like fallback slots and counted as estimated, never defaulted to zero.

#### Scenario: Empty estimate
- **WHEN** the API call succeeds but returns no data
- **THEN** the stored fallback is used

### Requirement: Fail loudly without usable data
If any slot of the horizon cannot be filled from stored Open-Meteo data (including when no baselines exist), the system SHALL raise `PVForecastError` and record a critical forecast error.

#### Scenario: No coverage
- **WHEN** the API fails and no stored baselines exist
- **THEN** `PVForecastError` is raised and no schedule is planned from fabricated PV

### Requirement: Estimated slots are not persisted as baselines
Slots filled by estimation SHALL NOT be written to the stored Open-Meteo baseline (`openmeteo_pv_forecast_kwh`), so later runs still count them as missing and training data contains only real Open-Meteo values.

#### Scenario: Outage lasts several planner runs
- **WHEN** the API stays down across consecutive runs and some slots were estimated in the first run
- **THEN** the second run reports the same slots as estimated and the stored baseline for them is still absent

### Requirement: Aurora inference never uses a zero baseline
When the Open-Meteo baseline for Aurora inference cannot be obtained (no usable stored data), inference SHALL abort without storing forecasts, leaving previous rows untouched, instead of substituting zeros.

#### Scenario: Baseline unavailable during inference
- **WHEN** `PVForecastError` is raised while fetching the baseline for inference
- **THEN** no forecast rows are stored and no zero-PV Aurora forecast reaches the planner

### Requirement: Planner DB forecast fills uncovered PV slots from time of day
When building the planner's Aurora/DB forecast for the price horizon, PV for slots without a stored row SHALL be the stored PV at the same local time of day from the nearest stored day (latest earlier day, else earliest later day), never a carried-forward last stored slot and never a default zero. Genuine small gaps (1-2 slots between stored slots) SHALL be linearly interpolated.

#### Scenario: Filled PV slots are flagged and reported
- **WHEN** PV for a slot without a stored row is filled by same-time-of-day substitution or interpolation
- **THEN** filled slots SHALL be flagged `pv_estimated`, counted, and reported through the degraded forecast status

#### Scenario: No stored rows on fresh install
- **WHEN** no stored rows exist at all (fresh install, learning period)
- **THEN** no health error SHALL be recorded

#### Scenario: Stored coverage ends before the horizon
- **WHEN** stored rows end at night and the horizon continues into the next days
- **THEN** daytime slots beyond coverage carry daytime PV values, not the last stored zero

#### Scenario: Small interior gap
- **WHEN** one or two slots between stored slots have no row
- **THEN** their PV is interpolated between the neighbouring stored slots

#### Scenario: No stored rows
- **WHEN** no stored rows exist (fresh install / learning period)
- **THEN** no forecast error or banner is recorded; only an info log

### Requirement: Stored baseline slot matching by instant
The stored-forecast fallbacks (stored Open-Meteo baselines and the DB forecast slots) SHALL match stored rows to price slots by the same canonical UTC instant key as the live path, independent of datetime type and DST fold.

#### Scenario: Stored baseline in the repeated hour
- **WHEN** a stored baseline exists for an instant in the repeated autumn hour and the price slot for that instant is a pandas Timestamp with fold=1
- **THEN** the stored value SHALL be used as an exact match and the slot SHALL NOT be counted as estimated
