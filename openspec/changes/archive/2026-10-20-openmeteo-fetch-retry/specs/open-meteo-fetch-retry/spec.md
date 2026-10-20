# Spec Delta

## Purpose
Defines how Darkstar retries transient Open-Meteo failures for PV and weather forecasts before falling back or reporting an error.

## ADDED Requirements

### Requirement: Transient Open-Meteo failures are retried with bounded backoff
The system SHALL retry an Open-Meteo PV or weather request that fails with a transient error (connection failure, timeout, HTTP 5xx or HTTP 429) up to 3 attempts in total, waiting with increasing delay between attempts, and the total retry wait per request SHALL NOT exceed 10 seconds.

#### Scenario: Transient failure then success
- **WHEN** the first request to Open-Meteo returns HTTP 503 and the second succeeds
- **THEN** the system uses the second response as the live forecast
- **AND** no forecast error is recorded and no stored-estimate fallback is used

#### Scenario: Retries are bounded
- **WHEN** every attempt fails with a transient error
- **THEN** the system makes exactly 3 attempts and stops

### Requirement: Non-transient errors are not retried
The system SHALL NOT retry Open-Meteo requests that fail with non-transient errors, including HTTP 400, 401, 403, 422 and invalid configuration or model errors.

#### Scenario: Configuration error
- **WHEN** Open-Meteo returns HTTP 422 for a PV array request
- **THEN** the system makes a single attempt and proceeds directly to the existing failure handling

### Requirement: PV retries are per array
When fetching PV forecasts for multiple solar arrays, the system SHALL retry only the failing array's request and SHALL NOT re-request arrays that already succeeded within the same fetch.

#### Scenario: One array fails transiently
- **WHEN** array 1 succeeds and array 2 fails once with HTTP 503 and then succeeds
- **THEN** array 1 is requested exactly once and array 2 exactly twice
- **AND** the summed forecast contains both arrays

### Requirement: Fallback and error reporting happen after retries
The system SHALL apply the stored-forecast fallback (PV) or empty-weather handling, and record the forecast error, only after retries are exhausted or a non-transient error occurs.

#### Scenario: Persistent transient failure
- **WHEN** all PV attempts fail with HTTP 503
- **THEN** the system falls back to the stored Open-Meteo estimate as before
- **AND** if no stored estimate is usable, a PV forecast error is raised

### Requirement: Retries are logged
The system SHALL log each retry at WARNING level including the target (PV array or weather), attempt number, delay and error.

#### Scenario: Retry log
- **WHEN** a transient failure triggers a retry
- **THEN** a WARNING log entry identifies the attempt (e.g. "attempt 1/3") and the error
