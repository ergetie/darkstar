# Spec Delta

## ADDED Requirements

### Requirement: Load profile history requests retry transient failures
Each one-day history request for the load profile SHALL be retried a bounded number of times when it fails with a transient error (timeout, connection error, HTTP 5xx or 429), with backoff, under an overall deadline for the whole profile. Permanent errors (other 4xx) SHALL NOT be retried. Other callers of the history request SHALL keep their existing single-attempt behaviour.

#### Scenario: Chunk succeeds on retry
- **GIVEN** one day's request times out once and then succeeds
- **WHEN** the load profile is built
- **THEN** the profile is built from all seven days and no demo profile is used

#### Scenario: Permanent error is not retried
- **WHEN** a chunk returns HTTP 401 or 404
- **THEN** it is attempted once and treated as failed

#### Scenario: Overall deadline
- **WHEN** Home Assistant stays unresponsive
- **THEN** the build stops fetching at the deadline, or after consecutive chunks exhaust their retries, and falls back as specified below

### Requirement: Partial history window is used when enough days load
When some day chunks fail after retries and at least the minimum number of days succeeded, the profile SHALL use per-slot coverage averaging (`energy-recording`) over the days fetched, not a division by seven or by the number of days fetched. A chunk that failed SHALL contribute neither energy nor covered seconds, and the number of days fetched SHALL be used only for the minimum. Fewer days than the minimum SHALL be a transient failure, judged before any data-quality rule.

#### Scenario: Six of seven days
- **GIVEN** six chunks succeed and one fails after retries
- **THEN** the profile is the per-slot coverage average of the six days and its status reports a partial window

#### Scenario: Fetch completeness is judged before data quality
- **GIVEN** fewer than the minimum number of days were fetched, and the fetched days would also fail the supported-slot rule (`energy-recording`)
- **THEN** the build is a transient failure (last good profile or demo/synthetic fallback), not a data problem

#### Scenario: Data quality after the floor is met
- **GIVEN** at least the minimum number of days were fetched but fewer than 48 of 96 slots have valid data, or the history is empty or implausible
- **THEN** the existing demo or synthetic fallback and message apply, the stored profile is not used and no cooldown starts

#### Scenario: Too few days
- **GIVEN** fewer than the minimum number of days succeed
- **THEN** the last good profile is used if available, otherwise the existing demo or synthetic fallback applies

### Requirement: Last good load profile survives transient failures
A profile built from live history SHALL be kept as the last good profile in memory and in an atomically written file under `data/`, with creation time, sensor and days used. On a transient fetch failure it SHALL be returned instead of the demo profile if valid, from the same sensor and not older than the maximum age.

#### Scenario: Transient failure after a good profile
- **GIVEN** a good profile built an hour ago
- **WHEN** every history request fails
- **THEN** that profile is returned instead of the flat demo profile

#### Scenario: Restart during an outage
- **GIVEN** a stored profile file and Home Assistant unreachable at start
- **THEN** the stored profile is used

### Requirement: Stored profile is validated and never masks data problems
A stored profile SHALL be ignored when it is older than the maximum age, from another sensor, timestamped in the future, or not 96 finite non-negative values within the plausibility bound. Empty history, implausible data and a missing sensor configuration SHALL keep their existing fallback and messaging.

#### Scenario: Stale, mismatched or corrupt profile
- **WHEN** the stored profile is older than the maximum age, was built from another sensor, has a future timestamp, or fails validation
- **THEN** it is ignored and the existing fallback applies

#### Scenario: Data problems are not masked
- **WHEN** history is fetched but empty or discarded as implausible
- **THEN** the stored profile is not used and the existing degraded message applies

### Requirement: A failed build starts a cooldown and concurrent builds are shared
After a build ends in transient failure, calls within the cooldown for the same sensor SHALL skip fetching and return the fallback chain result. Concurrent calls in one event loop SHALL share one in-flight build. Success SHALL clear the cooldown and an explicit refresh SHALL bypass it. An outage SHALL cost at most one build deadline per cooldown window.

#### Scenario: Calls during the cooldown
- **GIVEN** a build ended in transient failure less than the cooldown ago
- **WHEN** the planner, an API route or a second planner step asks for the profile
- **THEN** no history request is made and the last good profile, else the synthetic or demo profile, is returned with the matching status

#### Scenario: Cooldown expiry
- **WHEN** the cooldown has elapsed and a call arrives
- **THEN** one new build is attempted

#### Scenario: Concurrent calls
- **WHEN** two calls arrive while a build is running
- **THEN** only one set of history requests is made and both receive the same profile

#### Scenario: Recovery clears the memo
- **WHEN** a build succeeds
- **THEN** the cooldown is cleared and later calls fetch normally

#### Scenario: Sensor changed or explicit refresh
- **WHEN** the configured load sensor differs from the one that failed, or the debug endpoint requests a refresh
- **THEN** the cooldown does not apply

#### Scenario: Outage cost bound
- **GIVEN** Home Assistant is unreachable and ten calls arrive within one cooldown window
- **THEN** at most one build deadline of request time is spent in total

### Requirement: Fallback status describes the profile actually in use
Using the last good profile SHALL set a degraded load-forecast status stating it is a stored profile, its age and the sensor, not "demo data". A partial window SHALL be reported as such. A full live fetch SHALL clear a status set by this path, without clearing statuses set by the ML forecast.

#### Scenario: Stored profile in use
- **WHEN** the stored profile is returned
- **THEN** the banner says a stored load profile of the given age is in use because history could not be fetched, and never says demo data or 0.5 kWh flat

#### Scenario: Recovery
- **WHEN** the next build succeeds from all days
- **THEN** the stored-profile or partial status is cleared
