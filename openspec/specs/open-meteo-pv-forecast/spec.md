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

The calculation SHALL use `calculate_physics_pv()` with:
- `radiation_w_m2` = shortwave radiation from Open-Meteo (W/m²)
- `solar_arrays` = array configs including `kwp`, `tilt`, and `azimuth`
- `slot_start` = timestamp for solar position calculation
- `latitude` / `longitude` = system location

The solar azimuth SHALL be converted from North convention (0°=North, clockwise) to South convention (0°=South, positive=West) before calculating POA irradiance.

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

The live Open-Meteo forecast path SHALL map PV power to each requested slot by direct timestamp lookup, so that mapping cost does not grow with the length of the fetched solar series. The mapped values MUST be identical to matching each slot's 15-minute-rounded start time against the series by UTC instant.

#### Scenario: Slot matches a series timestamp in a different timezone
- **WHEN** a slot start is a pytz-aware local timestamp and the series key for the same instant is a fixed-offset aware datetime
- **THEN** the slot SHALL receive that key's summed watts converted to kWh (`watts * 0.25 / 1000`)

#### Scenario: Slot has no matching series timestamp
- **WHEN** no series key equals the slot's rounded start instant
- **THEN** the slot's PV forecast SHALL be 0.0 kWh

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
