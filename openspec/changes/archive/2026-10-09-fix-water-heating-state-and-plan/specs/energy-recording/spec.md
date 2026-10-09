## MODIFIED Requirements

### Requirement: Per-device water energy storage
The recorder SHALL store per-device water energy in versioned existing slot observation metadata, keyed by heater ID, without a database schema change. Reads SHALL return attributable energy, measurement source, coverage and active-energy semantics. Accepted corrections SHALL update water energy and its device metadata together; unrelated and retained authoritative metadata SHALL be preserved.

#### Scenario: Per-device energy stored as JSON
- **WHEN** the recorder stores a slot observation with two active water heaters
- **THEN** the observation SHALL include a field (e.g., `water_heater_energy`) containing `{"main_tank": 0.75, "upstairs_tank": 0.50}`

#### Scenario: Single heater backward compatible
- **WHEN** only one heater is active
- **THEN** `water_kwh` SHALL contain the total (same as before)
- **AND** `water_heater_energy` SHALL contain `{"main_tank": 0.75}`

#### Scenario: No active heaters
- **WHEN** no water heaters are enabled or none are heating
- **THEN** `water_kwh` SHALL be `0.0`
- **AND** known measured idle heaters SHALL have explicit zero-valued entries; when no heaters are enabled the mapping SHALL be `{}` or omitted

#### Scenario: Stored mapping survives restart and correction
- **WHEN** the recorder writes heater A at 0.75 kWh and heater B at 0.50 kWh through the observation store and the process restarts
- **THEN** reading the slot SHALL return both device values and their source/semantics metadata
- **AND** a subsequent accepted correction to A SHALL update its value and attribution together without losing unrelated metadata

#### Scenario: Legacy aggregate cannot establish ownership
- **WHEN** a legacy observation contains only aggregate water energy and sole-heater ownership for that window cannot be established
- **THEN** the reader SHALL NOT assign or split that energy among current heater IDs
- **AND** it SHALL attempt reconstruction from available power history and otherwise report unavailable device attribution

#### Scenario: Legacy energy semantics are not invented
- **WHEN** historical water energy lacks evidence that an idle cutoff was applied
- **THEN** it SHALL retain legacy semantics and SHALL NOT be relabelled as filtered active energy
- **AND** a current device count of one alone SHALL NOT certify historical sole ownership

## ADDED Requirements

### Requirement: Consistent per-heater active-power normalization
The system SHALL apply each heater's finite non-negative `idle_power_threshold_kw` after power-unit conversion and before integrating energy. Samples below the cutoff SHALL contribute zero active-heating power; samples at or above the cutoff SHALL retain their normalized power. The default SHALL be 0 for backward compatibility. History integration, snapshot fallback, backfill, recent planner progress, live load disaggregation and heating activity detection SHALL use the same rule. Filtered water energy SHALL be subtracted from total load; excluded idle consumption SHALL remain in household base load, with metered grid energy unchanged.

#### Scenario: Idle draw is household consumption
- **WHEN** a heater draws 0.06 kW throughout a 15-minute slot with cutoff 0.10 kW
- **THEN** its active water energy SHALL be zero
- **AND** the 0.015 kWh idle consumption SHALL remain in base load
- **AND** it SHALL NOT be detected as actively heating

#### Scenario: Mixed slot is filtered before integration
- **WHEN** valid heater samples indicate 3 kW for 10 minutes and 0.06 kW for 5 minutes with cutoff 0.10 kW
- **THEN** active water energy SHALL be 0.50 kWh, not the integral of idle draw and not a threshold applied to slot-average power
- **AND** load isolation SHALL subtract 0.50 kWh exactly once

#### Scenario: Unit conversion and boundary are consistent
- **WHEN** a sensor reports 100 W or 0.10 kW with cutoff 0.10 kW
- **THEN** both SHALL retain 0.10 kW active power
- **AND** a 99 W sample SHALL contribute zero

#### Scenario: Fallback and backfill match live recording
- **WHEN** live history, snapshot fallback, backfill or recent progress handles the same normalized samples and configured cutoff
- **THEN** they SHALL classify idle and active power consistently and retain truthful measurement provenance
