## MODIFIED Requirements

### Requirement: Both sides share completed-slot coverage
Only completed timezone-aware 15-minute recorded slots SHALL enter the comparison. Required household/water/EV and import/export energies SHALL be finite and nonnegative; required import/export prices SHALL be finite. Missing required values SHALL NOT be filled with zero. Legitimately disabled demand components SHALL use their recorded zero values. The one exception is a water component whose recorder method is `unknown` because the water heater is unmeasured (enabled heater with no sensor, or configured water sensor unavailable): its null or zero `water_kwh` is not a filled value, because under `derived_history` the recorded `load_kwh` is the total metered load and still contains the unmeasured water energy, so `load_kwh + water_kwh + ev_charging_kwh` equals total metered demand. Such a slot is included only when every other relevant component is eligible, the load method is `derived_history`, and the base-load clamp cannot have triggered (rejected when `ev_charging_kwh > 0` and `load_kwh == 0`). Unknown EV or load, and water unknown with snapshot, mixed or disaggregated load, remain rejected. The system SHALL reject placeholder rows, explicit exclusions, backfills and known snapshot/mixed essential demand/grid readings. For configured batteries, charge and discharge SHALL be finite nonnegative values from recorder-owned `power_history` or `derived_history` components; snapshots, mixed, disabled-zero, unconfigured-zero, invalid, unknown or backfilled provenance SHALL not qualify. Valid legacy `source: recorder` inputs SHALL remain usable without claiming verified provenance; modern metadata checks SHALL concern only components required by this bill calculation and configured-battery flows, not PV or SoC. Numerical records and quality metadata SHALL NOT be changed.

The same eligible slots SHALL enter both sides. Missing or rejected slots SHALL increase `excluded_slots` and SHALL NOT invalidate other eligible slots or require a SoC restart anchor. Coverage SHALL count expected completed slots in elapsed UTC time and satisfy `covered_slots + excluded_slots = total_slots`. The ongoing and future slots SHALL NOT count toward expected completed coverage. `through` SHALL identify the last included slot's exclusive end. A result with excluded slots and some usable data SHALL be visibly partial; a result without usable data SHALL contain no amounts.

#### Scenario: Missing hour
- **WHEN** a completed 96-slot day contains an unrecorded hour and the remaining inputs are valid
- **THEN** coverage is 92 covered, 96 total and 4 excluded
- **AND** both bill totals use those same 92 slots without dropping an extra restart slot

#### Scenario: Missing required energy
- **WHEN** a slot has null household consumption but nonzero measured imports
- **THEN** that slot is excluded from both sides rather than treated as zero consumption

#### Scenario: Incomplete current slot
- **WHEN** the current slot has started but not ended
- **THEN** it is absent from comparison amounts and completed-slot coverage

#### Scenario: No usable inputs
- **WHEN** completed records exist but every record fails a required input check
- **THEN** coverage has zero covered slots and no comparison amount is returned

#### Scenario: Unmeasured water included with a note (PLL case)
- **GIVEN** a slot where water method is `unknown` (enabled heater with empty sensor), `water_kwh` is 0.0, load method is `derived_history`, and all other components are eligible
- **THEN** the slot is included and baseline demand equals `load_kwh + 0 + ev_charging_kwh`
- **AND** the slot counts in `coverage.water_unmeasured_slots`

#### Scenario: Water sensor unavailable included with a note
- **GIVEN** a slot where the configured water sensor was unavailable, `water_kwh` is null, load method is `derived_history`, and all other components are eligible
- **THEN** the slot is included with `water_kwh` treated as 0 and counted in `coverage.water_unmeasured_slots`

#### Scenario: Disaggregated load with unknown water is rejected
- **GIVEN** a slot where water method is `unknown` and load method is `snapshot` or `mixed` (disaggregator or snapshot path)
- **THEN** the slot is excluded

#### Scenario: Base-load clamp suspected is rejected
- **GIVEN** a slot where water method is `unknown`, `ev_charging_kwh` is above 0 and `load_kwh` is 0
- **THEN** the slot is excluded

#### Scenario: EV or load unknown is rejected
- **GIVEN** a slot where the EV or load method is `unknown`
- **THEN** the slot is excluded, whatever the water method

## ADDED Requirements

### Requirement: Response reports unmeasured-water slots
The response SHALL include `coverage.water_unmeasured_slots` and `coverage.water_unmeasured_hours` (slots times 0.25) for every period, both 0 when none apply, without changing status or amounts. The UI SHALL show a small warning note when the count is above 0.

#### Scenario: Note present
- **WHEN** 8 included slots have unmeasured water
- **THEN** `water_unmeasured_slots` is 8, `water_unmeasured_hours` is 2.0 and the UI shows "Water not measured for 2 h, included"

#### Scenario: Note absent
- **WHEN** no included slot has unmeasured water
- **THEN** both fields are 0 and no note is rendered
