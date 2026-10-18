## MODIFIED Requirements

### Requirement: Stale sensor fail-safe
If any per-phase grid current value is missing or older than `sensor_stale_after_s` (default 30 s), the balancer SHALL immediately reduce the EV to `min_current_a`. If staleness persists beyond one resume cycle (`resume_delay_s`), the balancer SHALL pause charging. Balancing decisions SHALL never be made from stale data as if it were fresh.

The balancer status message for this condition SHALL name each affected phase as "L1".."L3", distinguish a missing reading ("no reading", no age) from a stale one (reporting the actual age of the reading, measured as described below), and SHALL report the time the balancer has been in the stale/paused state separately, labelled as a pause duration, never conflated with sensor age.

A reading's age SHALL be measured from its reading-freshness timestamp as defined by the `ha-reading-freshness` capability (`last_reported`, falling back to `last_updated`, then `last_changed`) — i.e., from when HA last received a report, not from when the value last changed. A sensor that keeps reporting an unchanged value SHALL NOT be considered stale.

For a phase in power-sensor mode with a configured voltage entity, "the per-phase grid current value" for staleness purposes SHALL be considered stale if either the power reading or the voltage reading is missing or older than `sensor_stale_after_s` — i.e., the fail-safe SHALL use the older of the two readings' timestamps. A phase with no voltage entity configured is not affected by this rule (it always uses the nominal fallback voltage, which has no staleness of its own).

#### Scenario: Phase sensor stops updating mid-charge
- **WHEN** the L1 sensor's last report is older than 30 s while the EV charges at 16 A
- **THEN** the balancer SHALL set the EV to 6 A
- **AND** if data is still stale 120 s later, charging SHALL be stopped

#### Scenario: Steady value still reported is not stale
- **WHEN** the L3 power reading has not changed for 45 s but its `last_reported` is 5 s old
- **THEN** L3 SHALL NOT be treated as stale and no fail-safe or notification SHALL occur

#### Scenario: Configured voltage entity goes stale
- **WHEN** L2 is in power-sensor mode with a configured voltage entity, the power reading is fresh, but the voltage entity's last report is older than `sensor_stale_after_s`
- **THEN** L2 SHALL be treated as stale by this fail-safe (same as a stale current/power reading)
- **AND** the balancer SHALL NOT substitute `load_balancing.nominal_voltage_v` in place of the stale voltage entity

#### Scenario: No voltage entity configured is not staleness
- **WHEN** L3 is in power-sensor mode with no voltage entity configured, and the power reading is fresh
- **THEN** L3 SHALL NOT be considered stale on account of having no voltage entity
- **AND** `load_balancing.nominal_voltage_v` SHALL be used for the conversion

#### Scenario: Stale reading message shows sensor age
- **WHEN** phase L2's last reading is 90 s old and exceeds the stale threshold
- **THEN** the message names L2 and shows an age of about 90 s

#### Scenario: Missing reading message
- **WHEN** a phase has no reading
- **THEN** the message names the phase as "no reading", not with an age

#### Scenario: Pause duration reported separately
- **WHEN** staleness has lasted past `resume_delay_s` and charging is paused
- **THEN** the message states the pause duration separately from the sensor age
