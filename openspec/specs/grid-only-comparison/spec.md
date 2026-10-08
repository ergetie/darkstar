# Grid-only Comparison

## Purpose

Defines a per-slot comparison of the same recorded consumption bought entirely from the grid against measured DS electricity costs and configured battery wear, with matched completed-slot coverage and chart segments that preserve excluded intervals.

## Requirements

### Requirement: Grid-only baseline prices all recorded consumption per slot
The system SHALL define the grid-only installation as covering the same recorded consumption at the same times entirely from the grid, with no solar or stationary battery. For every eligible completed slot, baseline demand SHALL equal `load_kwh + water_kwh + ev_charging_kwh`, and baseline electricity cost SHALL equal that demand multiplied by the recorded `import_price_sek_kwh`. Household load is isolated from EV/water consumption; each component SHALL be counted exactly once. Stationary battery charging SHALL NOT be added to demand, and recorded PV SHALL NOT be deducted from baseline demand. The system SHALL NOT substitute an average tariff, monthly tariff, forecast price or current-config recomputation for recorded slot prices.

#### Scenario: Household and controlled loads
- **WHEN** one slot contains household load 1 kWh, water 0.5 kWh, EV 2 kWh and import price 2 kr/kWh
- **THEN** baseline demand is 3.5 kWh and grid-only cost is 7 kr
- **AND** battery charging and PV generation do not alter that baseline cost

#### Scenario: Slot pricing differs from an average-price benchmark
- **WHEN** consumption is 1 kWh at 1 kr/kWh and 3 kWh at 3 kr/kWh
- **THEN** grid-only cost is 10 kr, not 4 kWh multiplied by the 2 kr/kWh average

### Requirement: DS comparison uses measured electricity and configured wear
The DS side SHALL use recorded gross grid flows: `import_kwh * import_price_sek_kwh - export_kwh * export_price_sek_kwh`. For configured batteries, DS cost SHALL include wear calculated by the existing configured formula `(battery_charge_kwh + battery_discharge_kwh) * battery_cycle_cost_kwh * 0.5` on those same eligible slots. Any finite configured cycle-cost value SHALL be applied as configured; malformed or non-finite configured cycle-cost values SHALL make configured-battery slots unavailable rather than silently substituting zero. Grid-only wear SHALL be zero. The comparison SHALL expose DS electricity cost and DS wear separately, while its DS total and solid chart line include wear. It SHALL NOT reconstruct grid cost from PV, battery flows, efficiencies or net energy. `saving_sek` SHALL equal grid-only cost minus DS electricity cost minus DS wear over exactly the same included slots. Positive values mean a lower wear-inclusive whole-installation cost; negative values mean a higher wear-inclusive whole-installation cost. Neither side SHALL include stored-energy valuation, fixed subscription charges or capital costs. Actual electricity cost and the existing separate wear-inclusive figure SHALL remain available.

#### Scenario: Gross metered overlap
- **WHEN** demand is 3.5 kWh, grid import is 1 kWh, export is 0.5 kWh, import price is 2 kr/kWh and export price is 1 kr/kWh
- **THEN** grid-only cost is 7 kr, DS cost is 1.5 kr and saving is 5.5 kr
- **AND** measured imports and exports are priced separately even though their net is 0.5 kWh

#### Scenario: Wear is included once on the DS side
- **WHEN** grid-only cost is 5 kr, DS electricity cost is 8 kr, and configured battery throughput incurs 1 kr of wear
- **THEN** DS comparison cost is 9 kr and saving is -4 kr
- **AND** Battery Charge remains informational and is not deducted from DS cost a second time

### Requirement: Comparison preserves zero and negative tariffs
Finite zero and negative import/export prices SHALL retain their signs throughout both comparison sides. Aggregation SHALL use full precision before rounding response values to three decimals and displayed values to two decimals. Savings SHALL NOT be clamped to zero or converted to a percentage divided by potentially zero/negative costs.

#### Scenario: Negative import price
- **WHEN** demand is 2 kWh, DS imports 1 kWh, there is no export, and import price is -1 kr/kWh
- **THEN** grid-only cost is -2 kr, DS cost is -1 kr and saving is -1 kr

#### Scenario: Zero price
- **WHEN** all applicable slot prices are zero
- **THEN** both bill totals and saving are zero, not missing

### Requirement: Comparison does not depend on battery or solar models
The comparison SHALL be available for any installation with eligible recorded inputs, including solar-only, battery-only and grid-only installations. It SHALL NOT require battery presence, SoC endpoints, battery capacity/limits/efficiencies, PV readings, calibration history, future prices or S-index. When no battery is configured, battery flows are not required and wear SHALL be zero. When a battery is configured, finite nonnegative charge and discharge readings with eligible recorder provenance are required for both sides on each included slot; missing or known snapshot, mixed, invalid, backfilled or unconfigured-zero readings SHALL exclude that slot rather than become zero. The financial endpoint SHALL NOT invoke self-use simulation, battery calibration, calibration caching or planner optimization to produce the comparison.

#### Scenario: Solar-only installation
- **WHEN** solar is configured, no battery exists and relevant recorded inputs are usable
- **THEN** the grid-only comparison is returned without a no-battery exclusion

#### Scenario: Missing battery and PV measurements without a battery
- **WHEN** relevant demand/grid energies and prices are usable, no battery is configured, and SoC, battery flows and PV measurements are missing
- **THEN** the slot remains eligible for grid-only accounting with zero wear

#### Scenario: Configured battery measurements are missing
- **WHEN** a battery is configured and a slot lacks charge or discharge measurements
- **THEN** the slot is excluded from both sides and is never assigned zero wear by assumption

#### Scenario: Ideal grid-only installation
- **WHEN** solar and battery are absent, measured imports equal total demand and exports are zero
- **THEN** comparison saving is zero within rounding

### Requirement: Both sides share completed-slot coverage
Only completed timezone-aware 15-minute recorded slots SHALL enter the comparison. Required household/water/EV and import/export energies SHALL be finite and nonnegative; required import/export prices SHALL be finite. Missing required values SHALL NOT be filled with zero. Legitimately disabled demand components SHALL use their recorded zero values. The system SHALL reject placeholder rows, explicit exclusions, backfills and known snapshot/mixed essential demand/grid readings. For configured batteries, charge and discharge SHALL be finite nonnegative values from recorder-owned `power_history` or `derived_history` components; snapshots, mixed, disabled-zero, unconfigured-zero, invalid, unknown or backfilled provenance SHALL not qualify. Valid legacy `source: recorder` inputs SHALL remain usable without claiming verified provenance; modern metadata checks SHALL concern only components required by this bill calculation and configured-battery flows, not PV or SoC. Numerical records and quality metadata SHALL NOT be changed.

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

### Requirement: Summary and chart totals reconcile
Comparison amounts SHALL be aggregated by installation-local hour for one-day periods and local day for longer periods, ordered chronologically in UTC. Both cumulative series SHALL sum exactly the same eligible slot set. Repeated DST hours SHALL retain distinct UTC identities and SHALL NOT collapse into one bucket. DST day coverage SHALL reflect elapsed slots, such as 92 or 100 rather than a hard-coded 96. Final cumulative DS and grid-only costs SHALL equal their summary totals within response rounding, and their difference SHALL equal `saving_sek`. Empty/excluded buckets SHALL have no invented contribution; partially covered buckets SHALL contain only eligible slots.

#### Scenario: Final endpoints
- **WHEN** the covered DS bill is 10 kr and grid-only bill is 30 kr
- **THEN** final cumulative points are 10 kr and 30 kr and saving is 20 kr

#### Scenario: Repeated local hour
- **WHEN** the clock falls back and two local 02:00 hours occur
- **THEN** they remain separate offset-qualified buckets in UTC chronological order
- **AND** coverage includes every elapsed completed slot once

### Requirement: Covered segments expose gaps independently of buckets
Amount-bearing comparisons SHALL expose `segments` as maximal runs of eligible slots contiguous in elapsed UTC time. Each segment SHALL contain offset-qualified local ISO `start`, exclusive `end`, and boundary `points` with `at`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`. Boundary points SHALL include the segment start and every included slot's exclusive end in UTC chronological order. The first segment SHALL start at zero cumulative costs; each later segment SHALL start at the totals accumulated from all earlier eligible slots. No segment SHALL contain an excluded slot or cross an excluded interval. Hour/day boundaries SHALL NOT split an otherwise contiguous segment.

Bucket totals and segment boundary totals SHALL derive from the same unrounded slot costs and reconcile within response rounding. Segments SHALL preserve gaps inside partially covered buckets, while bucket points SHALL retain hourly/daily costs for bars and readouts. The final segment endpoint SHALL equal the comparison summaries within response rounding.

#### Scenario: Gap inside an hourly bucket
- **WHEN** 10:00, 10:30 and 10:45 are eligible but the 10:15 slot is excluded
- **THEN** the 10:00 hourly bucket contains only the three eligible slots' costs
- **AND** covered segments stop at 10:15 and resume at 10:30 without representing the excluded interval
- **AND** the resumed segment starts at the earlier accumulated totals

#### Scenario: Gap inside a daily bucket
- **WHEN** a daily bucket contains usable morning and evening slots separated by an excluded hour
- **THEN** the daily bucket sums only eligible costs and covered segments expose the excluded hour separately

#### Scenario: Contiguous coverage crosses a bucket boundary
- **WHEN** eligible slots are contiguous across an hour, midnight or DST transition
- **THEN** they remain one covered segment while bucket totals retain their distinct local hour/day identities
