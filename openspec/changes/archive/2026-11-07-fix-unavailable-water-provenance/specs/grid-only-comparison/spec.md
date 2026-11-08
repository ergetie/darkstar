# Spec Delta

## MODIFIED Requirements

### Requirement: Both sides share completed-slot coverage
Only completed timezone-aware 15-minute recorded slots SHALL enter the comparison. Required household/water/EV and import/export energies SHALL be finite and nonnegative; required import/export prices SHALL be finite. Missing required values SHALL NOT be filled with zero. Legitimately disabled demand components SHALL use their recorded zero values. Every completed expected slot that does not enter the comparison SHALL be reported with exactly one machine reason code, never as an unexplained gap.

#### Scenario: Unmeasured water exception
- **WHEN** a water component's recorder method is `unknown` because the water heater is unmeasured (enabled heater with no sensor, or configured water sensor unavailable)
- **THEN** its null or zero `water_kwh` is not a filled value, because under `derived_history` the recorded `load_kwh` is the total metered load and still contains the unmeasured water energy, so `load_kwh + water_kwh + ev_charging_kwh` equals total metered demand
- **AND** such a slot is included only when every other relevant component is eligible, the load method is `derived_history`, and the base-load clamp cannot have triggered (rejected when `ev_charging_kwh > 0` and `load_kwh == 0`)
- **AND** unknown EV or load, and water unknown with snapshot, mixed or disaggregated load, remain rejected

#### Scenario: Rejected rows and battery flow provenance
- **WHEN** slots are checked for eligibility
- **THEN** the system SHALL reject placeholder rows, explicit exclusions, backfills and known snapshot/mixed essential demand/grid readings
- **AND** for configured batteries, charge and discharge SHALL be finite nonnegative values from recorder-owned `power_history` or `derived_history` components; snapshots, mixed, disabled-zero, unconfigured-zero, invalid, unknown or backfilled provenance SHALL not qualify

#### Scenario: Legacy recorder inputs and unchanged records
- **WHEN** inputs carry legacy `source: recorder` metadata
- **THEN** valid legacy inputs SHALL remain usable without claiming verified provenance
- **AND** modern metadata checks SHALL concern only components required by this bill calculation and configured-battery flows, not PV or SoC
- **AND** numerical records and quality metadata SHALL NOT be changed

#### Scenario: Same slots on both sides and coverage accounting
- **WHEN** coverage is computed
- **THEN** the same eligible slots SHALL enter both sides
- **AND** missing or rejected slots SHALL increase `excluded_slots` and SHALL NOT invalidate other eligible slots or require a SoC restart anchor
- **AND** coverage SHALL count expected completed slots in elapsed UTC time and satisfy `covered_slots + excluded_slots = total_slots`
- **AND** `coverage.excluded_by_reason` SHALL map each reason code to its slot count and sum to `excluded_slots`
- **AND** the ongoing and future slots SHALL NOT count toward expected completed coverage

#### Scenario: through and partial results
- **WHEN** the comparison result is built
- **THEN** `through` SHALL identify the last included slot's exclusive end
- **AND** a result with excluded slots and some usable data SHALL be visibly partial
- **AND** a result without usable data SHALL contain no amounts

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

### Requirement: Excluded spans are returned with a reason
The comparison SHALL return `excluded_spans`, a chronological list of maximal runs of contiguous excluded slots sharing one reason, each with offset-qualified local ISO `start`, exclusive `end`, `slots`, a machine `reason` code and an optional `component`. The field SHALL be additive and always present (empty when nothing is excluded), and existing fields SHALL be unchanged. The sum of `slots` SHALL equal `coverage.excluded_slots`.

#### Scenario: Unmeasured EV for two hours
- **GIVEN** eight consecutive completed slots whose EV component method is `unknown`
- **THEN** one span is returned with `slots` 8, reason `unknown_component` and component `ev`
- **AND** `coverage.excluded_by_reason.unknown_component` is 8

#### Scenario: Adjacent slots with different reasons
- **WHEN** an hour of `missing_slot` is followed directly by an hour of `missing_price`
- **THEN** two separate spans are returned, each with its own reason

#### Scenario: Nothing excluded
- **WHEN** every expected slot is eligible
- **THEN** `excluded_spans` is an empty list and `coverage.excluded_by_reason` is an empty object

#### Scenario: Older clients
- **WHEN** a client ignores the new fields
- **THEN** all previously documented fields keep their names, types and values

### Requirement: One reason per excluded slot by check order
Each excluded slot SHALL carry the first failing check of a fixed order that follows the eligibility checks, so the reason is deterministic and never a combination.

#### Scenario: Check order and codes
- **THEN** the order and codes are: no row (`missing_slot`); more than one row (`ambiguous_rows`); invalid battery wear cost (`battery_cost_invalid`); not recorder-owned, placeholder or backfill (`not_recorder`); user exclusion or exclude-from-comparison annotation (`user_excluded`); unsupported provenance schema (`unsupported_provenance`)
- **AND** then per relevant component in the order import, export, load, water, ev, battery charge, battery discharge: unconfigured (`unconfigured_sensor`), snapshot or mixed (`estimated_component`), unknown or not recorder-owned (`unknown_component`), disabled battery flow (`battery_disabled_zero`)
- **AND** then missing or invalid price (`missing_price`), missing or invalid energy (`missing_energy_value`), suspected base-load clamp (`clamp_hidden_demand`) and nonzero energy on a disabled component (`disabled_nonzero`)

#### Scenario: First failing check wins
- **GIVEN** a slot that is a backfill row with an unknown water component and a missing price
- **THEN** its reason is `not_recorder`

#### Scenario: Eligibility is unchanged
- **WHEN** the reasons are added
- **THEN** exactly the same slots are eligible and excluded as before, and amounts, segments and coverage counts are unchanged
