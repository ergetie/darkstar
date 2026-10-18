## MODIFIED Requirements

### Requirement: Outage indication
The UI SHALL make a PV forecast API outage visible using the existing alert banner, not a silent stale forecast. A fallback forecast SHALL set the PV forecast status to "degraded" (not "error") and record the estimated slot count. The banner SHALL escalate from warning to critical severity when more than 50% of horizon slots are estimated; the forecast is still used.

#### Scenario: API unreachable
- **WHEN** the open-meteo API is unreachable and the system is using the last successful stored forecast
- **THEN** the existing `SystemAlert` banner SHALL show a warning reading "API unreachable — using last known forecast (N slots estimated)"

#### Scenario: Majority of slots estimated
- **WHEN** the API is unreachable and more than 50% of horizon slots are estimated
- **THEN** the forecast is still used and the banner is shown at critical severity with the same text
