## MODIFIED Requirements

### Requirement: Car-side energy is recorded per slot
For every recorded slot with EV charger energy, the recorder SHALL also store car-side energy and its source next to the wallbox energy:
- `sensor`: the change of the charger's `energy_added_sensor` over the slot. A drop in the sensor value SHALL count as a session reset (post-reset value counts from zero) only when the new value is at or below a configurable near-zero threshold (default 0.5 kWh) Any other drop SHALL contribute 0 kWh (sensor drift).
- `soc`: when no sensor is configured, `ΔSoC / 100 × battery_capacity_kwh`, but only if SoC was fresh at both slot ends.
- Otherwise the value SHALL be NULL.

The sensor-derived value SHALL NOT exceed the slot's wallbox energy plus a tolerance, and SHALL be 0 when wallbox energy is approximately zero. When the aggregate EV energy for a slot is rejected by validation, the stored car energy SHALL be zeroed together with the per-charger wallbox energy.

The database column SHALL be added by an automatic migration.

#### Scenario: Sensor reset mid-slot
- **WHEN** the energy-added sensor reads 24.8 at slot start, resets to 0 and reads 0.6 at slot end, and the wallbox delivered at least 0.6 kWh
- **THEN** the slot's car energy SHALL be 0.6 kWh with source `sensor`

#### Scenario: Idle sensor drift
- **WHEN** the sensor reads 22.47, 22.36, 22.25 over idle slots with wallbox energy 7.5e-05 kWh per slot
- **THEN** each slot's car energy SHALL be 0 kWh

#### Scenario: Non-zero drop
- **WHEN** the sensor drops from 22.4 to 3.0 (not near zero) and then rises to 3.8 with wallbox energy 1.0 kWh
- **THEN** the drop SHALL contribute 0 and the 0.8 kWh rise SHALL count, capped by wallbox energy plus tolerance

#### Scenario: Car energy exceeds wallbox energy
- **WHEN** the sensor change is 2.0 kWh but wallbox energy is 1.0 kWh
- **THEN** car energy SHALL be capped to 1.0 kWh plus tolerance

#### Scenario: Rejected aggregate
- **WHEN** the slot's aggregate EV energy is rejected and zeroed
- **THEN** per-charger car energy SHALL also be zeroed

#### Scenario: SoC fallback
- **WHEN** no sensor is configured, the battery capacity is 64 kWh, and fresh SoC goes from 60% to 62% during the slot
- **THEN** the slot's car energy SHALL be 1.28 kWh with source `soc`

#### Scenario: Stale SoC
- **WHEN** no sensor is configured and SoC is stale at either slot end
- **THEN** the slot's car energy SHALL be NULL
