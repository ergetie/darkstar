## ADDED Requirements

### Requirement: Default-enabled user-controlled reporting
Darkstar SHALL expose `installation_stats.enabled` and `installation_stats.endpoint` in configuration, defaulting to `true` and `https://telemetry.wxl.se/api/ping` for new installations and upgrades. Missing values SHALL receive those defaults without overriding an explicitly saved boolean or endpoint. Endpoint validation SHALL require an absolute HTTPS URL with a hostname and no embedded credentials, query, or fragment. Invalid supplied configuration SHALL prevent reporting without blocking Darkstar startup.

#### Scenario: Upgrade without the section
- **WHEN** an existing installation upgrades with no `installation_stats` section
- **THEN** default merging supplies enabled reporting and the default endpoint
- **AND** no upgrade notice or forced onboarding is shown

#### Scenario: Explicit choices survive upgrades
- **WHEN** an installation with `enabled: false` and a custom HTTPS endpoint upgrades
- **THEN** both saved values remain unchanged
- **AND** no reporting request is sent

#### Scenario: Invalid configuration
- **WHEN** reporting configuration contains a non-boolean enabled value or an HTTP, relative, or credential-bearing endpoint
- **THEN** config save returns a validation error
- **AND** if invalid configuration is read at runtime the sender skips reporting while Darkstar continues operating

### Requirement: Minimal allowlisted payload
Each heartbeat SHALL contain exactly `installation_id`, `version`, `release_channel`, `installation_type`, `architecture`, and `inverter_profile`. The ID SHALL be random UUIDv4. Channel SHALL be `stable`, `dev`, or `unknown`; installation type SHALL be `ha_addon`, `docker`, or `unknown`; architecture SHALL be `amd64`, `aarch64`, or `unknown`. Profiles SHALL be deliberate shipped identifiers, `custom` for configured non-shipped identifiers, or `unknown` when unconfigured. The sender SHALL NOT send energy measurements, location, entity identifiers, capacities, configuration, secrets, host fingerprints, or client-generated timestamps.

#### Scenario: Configured add-on in shadow mode
- **WHEN** a stable aarch64 add-on using a built-in inverter profile sends a heartbeat while in shadow mode
- **THEN** it sends exactly the six permitted fields with channel `stable`, type `ha_addon`, and architecture `aarch64`
- **AND** the app version comes from the existing version helper
- **AND** shadow-mode status and energy data are absent

#### Scenario: Custom profile and incomplete setup
- **WHEN** a configured profile identifier is outside the shipped allowlist
- **THEN** the transmitted profile is `custom`, without its original name
- **AND** an installation with no configured profile reports `unknown`

#### Scenario: Channel and architecture classification
- **WHEN** the stable add-on runs a beta version and the host reports an architecture alias such as `x86_64`
- **THEN** the channel remains `stable` and architecture is normalized to `amd64`
- **AND** unknown deployment metadata produces `unknown` rather than host-specific strings

### Requirement: Persistent installation identity
The sender SHALL persist its random ID and previous attempt timestamp atomically in channel-scoped files under persistent `data/`. Restarts and upgrades within a channel SHALL retain the same ID. Stable/dev instances SHALL have distinct IDs even when their data directory is shared. State read/write failures or corrupted existing state SHALL skip reporting without creating ephemeral identities or failing Darkstar startup.

#### Scenario: Restart and upgrade
- **WHEN** an installation restarts or upgrades within its release channel
- **THEN** it retains the persisted ID and last-attempt schedule

#### Scenario: Stable and dev run together
- **WHEN** stable and dev add-ons use the same persistent data directory
- **THEN** each channel persists and reports a different ID
- **AND** neither overwrites the other's state

#### Scenario: Persistent state unavailable
- **WHEN** the state directory is unwritable or existing state is malformed
- **THEN** reporting is skipped with a brief local diagnostic
- **AND** planning, recording, and execution remain available

### Requirement: Daily reporting without restart bursts
The sender SHALL schedule its first due attempt after a randomized 1–15 minute startup delay and later attempts no sooner than 24 hours after the persisted previous attempt, with 0–15 minutes jitter. It SHALL record the attempt before sending, use a five-second total HTTP timeout, verify HTTPS certificates, refuse redirects, and avoid immediate retries or outage backlogs. It SHALL re-read current configuration before dispatch and while waiting, with at most 30 seconds between checks.

#### Scenario: First start
- **WHEN** enabled reporting starts without a prior attempt
- **THEN** the first heartbeat is delayed by 1–15 minutes
- **AND** later attempts follow the daily schedule

#### Scenario: Restart shortly after an attempt
- **WHEN** Darkstar restarts one hour after a recorded attempt
- **THEN** another attempt is not sent before the previous attempt is at least 24 hours old

#### Scenario: Receiver timeout or redirect
- **WHEN** the receiver times out, fails, or redirects
- **THEN** the attempt ends within the timeout and is not redirected or immediately retried
- **AND** no missed-ping backlog is accumulated

### Requirement: Runtime opt-out and isolated service lifecycle
Reporting SHALL run as an independently managed backend service that starts/stops with FastAPI lifespan. A successful UI config save SHALL notify it to re-evaluate settings. Disabling SHALL prevent subsequent request dispatch; an already-dispatched request can complete. Direct config edits SHALL be observed within 30 seconds. Reporting failures SHALL NOT block application startup/shutdown, planning, recording, or control, and shutdown SHALL cancel waiting/in-flight work and close its client.

#### Scenario: Disable from Settings
- **WHEN** a user successfully saves disabled reporting before the next dispatch
- **THEN** the sender wakes to re-evaluate configuration and sends no subsequent heartbeat
- **AND** the disabled choice survives a restart

#### Scenario: Manual edit or endpoint change
- **WHEN** configuration is edited directly to disable reporting or select another receiver
- **THEN** the sender observes it within 30 seconds
- **AND** any next due heartbeat uses the current enabled state and endpoint

#### Scenario: Network failure and shutdown
- **WHEN** the statistics service encounters a network/state error or Darkstar shuts down while it is waiting
- **THEN** the error is isolated or the wait is cancelled respectively
- **AND** energy-control services and application shutdown are not held up by the heartbeat schedule
