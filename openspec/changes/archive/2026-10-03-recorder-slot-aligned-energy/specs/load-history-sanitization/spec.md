## MODIFIED Requirements

### Requirement: Degraded load-forecast messaging is accurate
When the system falls back to a demo or synthetic load profile, the user-facing degraded status and log message SHALL distinguish between (a) no `input_sensors.load_power` configured and (b) a configured `load_power` whose history was empty or discarded as implausible, stating which sensor and why in case (b). The message SHALL NOT instruct the user to configure a sensor that is already configured, and SHALL NOT mention cumulative energy counters.

#### Scenario: Sensor configured but data discarded
- **WHEN** `input_sensors.load_power` is configured and the fetched history was discarded (e.g. the 500 kWh/day backstop triggered)
- **THEN** the degraded status and log message name the sensor and state that its data was discarded as implausible

#### Scenario: Sensor configured but history empty
- **WHEN** `input_sensors.load_power` is configured and its history has no valid samples in the 7-day window
- **THEN** the degraded status and log message name the sensor and state that no history was available

#### Scenario: Sensor genuinely not configured
- **WHEN** `input_sensors.load_power` is empty
- **THEN** the degraded message instructs the user to configure `load_power`

## REMOVED Requirements

### Requirement: Implausible cumulative-meter deltas are skipped, not fatal
**Reason**: The load profile is built from `load_power` history; there are no meter deltas or resets. The 500 kWh/day backstop and the per-slot clamp remain.
**Migration**: `recorder.max_meter_delta_kwh` is removed by startup config migration.
