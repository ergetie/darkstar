## Purpose

Surface PV forecast source, personalization status, and Open-Meteo outage state clearly in the UI.

## Requirements

### Requirement: Forecast source is visible
The UI SHALL show which PV forecast mode is active - open-meteo baseline only, open-meteo plus personal tuning, or open-meteo baseline with Aurora PV tuning disabled - on the Aurora Command Center.

#### Scenario: Baseline-only mode
- **WHEN** a home is running on the open-meteo baseline without an active ML nudge
- **THEN** the Aurora Command Center SHALL indicate the forecast source is "Open-Meteo baseline"
- **AND** SHALL NOT imply personalization is active

#### Scenario: Personalized mode
- **WHEN** the ML nudge is active (ramp weight > 0)
- **THEN** the Aurora Command Center SHALL indicate "Open-Meteo + personal tuning (active)"

#### Scenario: Aurora PV forecasting disabled
- **WHEN** `forecasting.aurora_pv_enabled` is false
- **THEN** the Aurora Command Center SHALL indicate that Aurora PV tuning is disabled
- **AND** SHALL indicate that PV is using the Open-Meteo baseline
- **AND** SHALL NOT imply that load forecasting has also been disabled

### Requirement: Personalization progress is visible
The UI SHALL communicate how close the system is to active/full personalization so the user understands when tuning will engage.

#### Scenario: Progress toward personalization
- **WHEN** a home is collecting data but the nudge is not yet at full weight
- **THEN** the indicator SHALL show progress (e.g. days collected vs the configured window, or "personalizing in ~N days")

#### Scenario: Optional dashboard badge
- **WHEN** the user views the Dashboard forecast
- **THEN** a compact badge MAY reflect the same source/mode at a glance
- **AND** it SHALL be consistent with the Aurora Command Center indicator

### Requirement: Outage indication
The UI SHALL make a PV forecast API outage visible using the existing alert banner, not a silent stale forecast.

#### Scenario: API unreachable
- **WHEN** the open-meteo API is unreachable and the system is using the last successful stored forecast
- **THEN** the existing `SystemAlert` banner SHALL show a warning that the API is unreachable and the last known forecast is in use
