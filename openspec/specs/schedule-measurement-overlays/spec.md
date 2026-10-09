## Purpose

The schedule history API and chart SHALL preserve planned water heating independently from supported actual measurements, so unavailable readings and unfinished slots do not erase the plan.

## Requirements

### Requirement: Unfinished slots retain their plan
The schedule history API and chart SHALL keep planned water heating and its per-device breakdown available independently of actual measurements. A slot SHALL be considered completed only when its end is at or before the current instant. Current and future slots SHALL NOT have their planned heating overwritten by observations or execution-history overlays. Any current actual telemetry SHALL remain separate from the plan.

#### Scenario: Current slot has a price-only placeholder
- **WHEN** it is 18:56, the 18:45–19:00 plan has water heating 3.1 kW and grid import 4.0 kW, and a price-only observation has default water energy zero
- **THEN** the plan SHALL retain water heating 3.1 kW and its corresponding planned per-device and grid values
- **AND** the unfinished slot SHALL NOT be marked as completed historical actuals
- **AND** the placeholder zero SHALL NOT become an actual water measurement

#### Scenario: Slot completes at the boundary
- **WHEN** the current instant reaches 19:00 for the 18:45–19:00 slot
- **THEN** the slot SHALL become eligible for supported completed measurements
- **AND** the original plan SHALL remain separately available for comparison

### Requirement: Actual water overlays require component evidence
Actual water values SHALL be presented only with supported water-component measurement provenance or valid legacy evidence explicitly establishing a water measurement. Integrated measurements and snapshot estimates SHALL retain distinct sources. A price-only row, a default zero column, or missing provenance SHALL NOT by itself establish a water actual. Unknown actuals SHALL remain unavailable; measured zero SHALL remain a valid actual. Aggregate and per-device actuals SHALL remain mutually consistent where attribution is known.

#### Scenario: Completed price-only row
- **WHEN** a completed slot contains prices but no supported water measurement
- **THEN** prices and the plan SHALL remain available and actual water SHALL be unavailable
- **AND** no per-device zero measurements SHALL be fabricated

#### Scenario: Completed measured zero
- **WHEN** a completed slot has supported water measurement provenance and measured water energy zero
- **THEN** actual water SHALL be zero with its source retained
- **AND** it SHALL be distinguishable from an unavailable actual

#### Scenario: Completed snapshot estimate
- **WHEN** a completed slot has an accepted snapshot-derived water estimate
- **THEN** its actual overlay SHALL be identified as an estimate rather than integrated history

#### Scenario: Legacy evidence and unknown attribution
- **WHEN** a legacy row has supported evidence for aggregate water but lacks per-device attribution
- **THEN** the aggregate actual SHALL remain available and per-device actuals SHALL remain unavailable
- **AND** rows without supported water evidence SHALL NOT be certified merely because their energy column is non-null

### Requirement: Water activity display uses active heating semantics
Chart/detail water activity SHALL consume the normalized active-heating signal and distinguish planned heating from supported actual heating. Below-cutoff idle power SHALL NOT create actual heating activity, and unavailable actuals SHALL NOT erase planned heating.

#### Scenario: Idle actual alongside planned heating
- **WHEN** a heater has planned heating but its actual power is below the configured active cutoff
- **THEN** planned heating SHALL remain visible as a plan
- **AND** the idle actual SHALL NOT be displayed as active heating
