## Purpose

Ensure the 7-day load profile built from a cumulative energy sensor's Home Assistant history is resilient to implausible meter-delta readings (e.g. nightly counter resets), and that degraded load-forecast messaging accurately reflects why the fallback profile is in use.

## Requirements

### Requirement: Implausible cumulative-meter deltas are skipped, not fatal
When building the 7-day load profile from a cumulative energy sensor's Home Assistant history, the system SHALL skip any single interval whose energy delta exceeds the configured `recorder.max_meter_delta_kwh` (default 50 kWh) instead of counting it, and SHALL continue processing subsequent intervals with the meter baseline advanced past the skipped reading. The number of skipped deltas (and the largest skipped value) SHALL be logged once per profile build. The existing 500 kWh/day whole-profile sanity bound SHALL remain as a final backstop.

#### Scenario: Nightly meter reset does not poison the profile
- **WHEN** a Fronius lifetime-energy sensor reads 0 overnight and jumps back to ~19,600 kWh each morning across the 7-day history window
- **THEN** each 0→lifetime jump is skipped as an implausible delta, the remaining genuine deltas produce a plausible daily profile (well under 500 kWh/day), and the demo fallback profile is NOT used

#### Scenario: Genuine consumption is unaffected
- **WHEN** the sensor history contains only plausible deltas (each below the configured maximum)
- **THEN** the resulting profile is identical to one built without the guard

#### Scenario: Skipped deltas are observable
- **WHEN** at least one delta was skipped during a profile build
- **THEN** a single log warning states how many deltas were skipped and the largest skipped value

### Requirement: Degraded load-forecast messaging is accurate
When the system falls back to a demo/synthetic load profile, the user-facing degraded status and log message SHALL distinguish between (a) no load sensor configured and (b) a configured sensor whose data was discarded as implausible, stating which sensor and why in case (b). The message SHALL NOT instruct the user to configure a sensor that is already configured.

#### Scenario: Sensor configured but data discarded
- **WHEN** `input_sensors.total_load_consumption` is configured and the fetched history was discarded (e.g. the 500 kWh/day backstop triggered)
- **THEN** the degraded status and log message name the sensor and state that its data was discarded as implausible, rather than claiming no sensor is configured

#### Scenario: Sensor genuinely not configured
- **WHEN** `input_sensors.total_load_consumption` is empty
- **THEN** the degraded message instructs the user to configure the sensor (current behavior preserved)
