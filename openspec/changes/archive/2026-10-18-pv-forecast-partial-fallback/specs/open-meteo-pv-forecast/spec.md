## ADDED Requirements

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
When building the planner's Aurora/DB forecast for the price horizon, PV for slots without a stored row SHALL be the stored PV at the same local time of day from the nearest stored day (latest earlier day, else earliest later day), never a carried-forward last stored slot and never a default zero. Genuine small gaps (1-2 slots between stored slots) SHALL be linearly interpolated. Filled slots SHALL be flagged `pv_estimated`, counted, and reported through the degraded forecast status. If no stored rows exist at all (fresh install, learning period), no health error SHALL be recorded.

#### Scenario: Stored coverage ends before the horizon
- **WHEN** stored rows end at night and the horizon continues into the next days
- **THEN** daytime slots beyond coverage carry daytime PV values, not the last stored zero

#### Scenario: Small interior gap
- **WHEN** one or two slots between stored slots have no row
- **THEN** their PV is interpolated between the neighbouring stored slots

#### Scenario: No stored rows
- **WHEN** no stored rows exist (fresh install / learning period)
- **THEN** no forecast error or banner is recorded; only an info log
