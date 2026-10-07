# No Darkstar Baseline

## Purpose

Defines the "without Darkstar" baseline: a replay of the period's recorded slots through a plain self-use inverter with the same battery, priced and worn like the real figures, used to show what Darkstar saves.

## Requirements
### Requirement: Baseline simulates a plain self-use inverter
The validated battery comparison SHALL replay the period's completed recorded slots through a plain self-use inverter with the same battery and calibrated model. Demand SHALL be `load_kwh + water_kwh + ev_charging_kwh` at the recorded times and amounts on both sides. Effective surplus SHALL be `eta_out * pv_kwh - demand`. Positive surplus SHALL charge up to battery room and configured charge power; battery discharge SHALL be capped by `max(0, load_kwh + water_kwh - eta_out * pv_kwh) / eta_out`, usable stored energy and configured discharge power. Remaining energy SHALL be priced through the shared grid model. The self-use battery SHALL NOT grid-charge or export from the battery, regardless of prices. It SHALL supply household/water deficits only. PV SHALL serve household/water demand first, then may supply EV demand; EV energy not supplied by PV SHALL import from the grid. It SHALL NOT copy Darkstar's blanket discharge block into mixed household/EV slots. The comparison SHALL NOT claim savings from scheduling these loads.

#### Scenario: PV surplus charges the battery first
- **WHEN** recorded PV is 1.0 kWh, demand is 0.4 kWh, output efficiency is 0.95 and battery limits allow charging
- **THEN** self-use charges `0.55 / 0.95` kWh in the recorded battery-flow boundary
- **AND** imports and exports nothing

#### Scenario: Surplus beyond the battery is exported
- **WHEN** the converted PV surplus exceeds battery room or the configured charge limit
- **THEN** only the permitted energy charges the battery and the shared grid model exports the remainder

#### Scenario: Deficit is covered by the battery
- **WHEN** demand exceeds converted PV and usable battery energy is available
- **THEN** the simulated battery supplies demand accounting for calibrated conversion losses
- **AND** only the uncovered deficit is imported

#### Scenario: Empty battery imports
- **WHEN** the simulated battery is at `min_soc_percent` and demand exceeds converted PV
- **THEN** the uncovered demand is imported

#### Scenario: No grid charging and no battery export
- **WHEN** prices are very low or very high without PV surplus or demand deficit respectively
- **THEN** self-use neither grid-charges nor exports battery energy

#### Scenario: Controlled loads retain their timing
- **WHEN** Darkstar charged an EV overnight and heated water in the afternoon
- **THEN** both comparison sides include those same amounts in those same slots
- **AND** plain self-use battery discharge may cover only household/water demand, with EV demand supplied by grid or remaining PV
- **AND** neither load is removed or rescheduled

### Requirement: Baseline battery accounting uses the configured limits and efficiencies
For the verified comparison, stored energy SHALL change by charge * eta_charge and discharge / eta_discharge, using calibrated effective factors in the recorded flow boundary. Capacity SHALL be configured battery.capacity_kwh. Configured minimum/maximum SoC and separate charge/discharge power limits SHALL be enforced. Missing or unreliable calibration SHALL withhold the verified comparison; it SHALL NOT substitute planner/default efficiencies as a learned comparison model. A separate configured-loss estimate may use the installation's configured charge/discharge efficiencies and limits under battery-comparison-calibration, and SHALL remain explicitly estimated. Inverter conversion and battery storage losses SHALL each be applied once.

#### Scenario: Efficiency applied
- **WHEN** 1.0 kWh is charged with validated eta_charge 0.92
- **THEN** simulated stored energy increases by 0.92 kWh

#### Scenario: Missing discharge calibration
- **WHEN** the discharge factor cannot be reliably calibrated
- **THEN** the verified comparison is unavailable rather than defaulting to 0.95
- **AND** any separately eligible configured-loss result remains labelled as an estimate

#### Scenario: Separate limits
- **WHEN** configured charge power is lower than discharge power
- **THEN** charging and discharging respect their respective limits

### Requirement: Baseline is simulated per run of consecutive usable slots from the real state of charge
The period's completed slots SHALL be split into maximal runs of consecutive usable slots, where adjacency is exactly 15 minutes of elapsed UTC time (DST-safe). A slot that is missing, or whose observation is ineligible (unsupported provenance, invalid essential energies or prices, invalid end SoC, placeholder rows), SHALL be excluded and SHALL break the run. The currently incomplete slot SHALL be excluded and the comparison through-time SHALL be exposed.

Each run SHALL be simulated independently from the real state of charge at its start: the first slot's valid trusted `soc_start_percent`, otherwise the immediately preceding contiguous slot's valid `soc_end_percent`. If neither exists, the run's first slot SHALL be dropped (counted as excluded) and the run SHALL start from that slot's measured `soc_end_percent`; a single-slot run that cannot be anchored SHALL be skipped. Both comparison sides SHALL share each run's common starting energy. A later slot's SoC or minimum configured SoC SHALL NOT substitute for missing starting measurements. The simulated state SHALL be carried forward within a run without resynchronizing to later real SoC, and SHALL NOT be carried across an excluded slot. Totals and saving SHALL be the sums of the per-run values. Cumulative comparison points SHALL be offset across runs so the final point equals the summed totals. Observations SHALL be processed in UTC chronological order across DST. The response SHALL carry `coverage` with `covered_slots`, `total_slots` and `excluded_slots`.

#### Scenario: Start from the previous slot's SoC
- **WHEN** the first slot has no start SoC and the immediately preceding slot ends at 60%
- **THEN** the simulation starts at 60%

#### Scenario: Leading slot without start SoC
- **WHEN** the first slot of a run has no start SoC and no contiguous preceding end SoC exists
- **THEN** that slot is dropped and excluded, and the run starts from its measured end SoC
- **AND** the result is an estimate with one fewer covered slot (for example 95 of 96)

#### Scenario: Unanchorable single-slot run
- **WHEN** a run consists of one slot with no start anchor
- **THEN** that run is skipped and its slot is excluded

#### Scenario: Recorded SoC does not steer the simulation
- **WHEN** the real battery charges from the grid overnight
- **THEN** the later real SoC does not reset the self-use simulation

#### Scenario: Gap in the middle
- **WHEN** a completed hour (four slots) is absent inside a 96-slot period
- **THEN** two runs are simulated, each from its own real start SoC
- **AND** coverage is 92 covered, 96 total, 4 excluded
- **AND** totals and saving are the sums across the two runs and the final cumulative points equal those totals
- **AND** the status is estimated, not verified

#### Scenario: Placeholder rows split runs
- **WHEN** recorded rows exist but hold empty placeholder values and no valid SoC or provenance
- **THEN** those slots are excluded and break runs rather than failing the period

#### Scenario: No usable run
- **WHEN** no slot of the period is usable
- **THEN** the comparison is unavailable with coverage of zero covered slots

#### Scenario: DST transition
- **WHEN** the clock repeats or skips a local hour
- **THEN** observations and adjacent-slot checks use elapsed UTC time
- **AND** the repeated local hour's slots stay in one run when they are consecutive in elapsed time

### Requirement: Baseline is priced and worn like the real figures
Both validated comparison sides SHALL use the same calibrated grid model and slot prices. The Darkstar side SHALL supply recorded battery actions; self-use SHALL supply simulated battery actions. Both SHALL price non-negative import/export derived from modeled net grid energy, without adding gross metered overlap to one side alone. A slot with missing essential prices SHALL be excluded, and the comparison is unavailable only when no usable run remains. Metered gross import/export costs SHALL remain available separately as actual electricity costs.

Each side's wear SHALL be `(charge_kwh + discharge_kwh) * battery_economics.battery_cycle_cost_kwh * 0.5`. Its comparison cost SHALL equal modeled grid cost plus wear minus the value of stored-energy change from the common start. Estimated saving SHALL equal self-use comparison cost minus Darkstar comparison cost (summed across runs). This SHALL be identified as a 15-minute battery-management estimate; exact sub-slot inverter responses SHALL NOT be asserted or compensated with an arbitrary penalty.

#### Scenario: Same pricing as the real figures
- **WHEN** either model imports 2.0 kWh at recorded import price 1.5
- **THEN** its import cost is 3.0 kr

#### Scenario: Saving includes wear on both sides
- **WHEN** self-use costs 40 kr including wear and Darkstar costs 30 kr including wear with equal stored-energy changes
- **THEN** estimated saving is 10 kr

#### Scenario: Metered overlap
- **WHEN** a recorded slot contains both import and export
- **THEN** actual costs retain both gross flows
- **AND** the estimated comparison applies shared net-grid accounting to both sides

#### Scenario: Identical actions
- **WHEN** recorded Darkstar battery actions, end energy and self-use actions are identical
- **THEN** estimated saving is zero within rounding

### Requirement: Saving values the energy left in the battery at the end of each run
Both comparison sides SHALL value their stored-energy change from the common run start using the same reference price: the mean recorded import price of that run's slots multiplied by `eta_out * eta_discharge` of the active basis. Each run SHALL value its stored energy at its own reference price; the period's reported reference price is the slot-weighted mean. Darkstar end energy SHALL come from the run's final slot's measured SoC; self-use end energy SHALL come from its simulation. Stored-energy difference SHALL remain real end energy minus simulated end energy. The difference in stored-energy value SHALL contribute positively to saving when Darkstar retains more energy at a positive reference price and negatively when it retains less. A slot with a missing end SoC or price SHALL be excluded rather than counting its missing adjustment as zero. Valid zero and negative prices SHALL retain their values.

#### Scenario: Real battery holds more
- **WHEN** Darkstar retains 4.6 kWh more than self-use and reference price after conversion losses is 2.4 kr/kWh
- **THEN** stored-energy difference adds 11.04 kr to estimated saving

#### Scenario: Real battery holds less
- **WHEN** Darkstar retains 2.0 kWh less and reference price is 2.0 kr/kWh
- **THEN** stored-energy difference subtracts 4.0 kr from estimated saving

#### Scenario: Real end state of charge unknown
- **WHEN** a slot has no valid real end SoC
- **THEN** that slot is excluded and breaks the run, and the comparison is unavailable only if no usable run remains

#### Scenario: No import prices
- **WHEN** essential import prices are missing for every slot
- **THEN** the comparison is unavailable rather than valuing unknown energy at zero
- **AND** slots with missing prices in an otherwise usable period are excluded, not valued at zero

#### Scenario: Negative valuation
- **WHEN** the mean import price is negative
- **THEN** the stored-energy reference price remains negative and is explained as a valuation assumption

### Requirement: Simulation exposes the final state of charge
The baseline simulation SHALL expose the simulated state of charge after the last slot in addition to the per-slot flows, without changing the per-slot flows.

#### Scenario: Final state of charge
- **WHEN** a 10 kWh battery starts at 50 %, charges 0.6 kWh and then discharges 1.0 kWh at efficiency 1.0
- **THEN** the simulated final state of charge is 46 %

### Requirement: Baseline is unavailable without a battery
When system.has_battery is false, no battery comparison SHALL be computed or shown. Empty periods SHALL have no comparison amounts. A period with at least one usable run SHALL return a clearly labelled estimate (basis configured_losses) when strict calibration is insufficient, fails its gates, or any slot of the period is excluded, preserving the actual calibration status/reason and any genuine diagnostics. The verified basis SHALL be returned only when every expected slot is usable, the slots form a single run, they match the calibration cohort and strict period validation passes; a period with excluded slots SHALL NEVER be labelled verified. Only when no usable run exists, including when every slot has invalid or missing required measurements, prices or state-of-charge anchors, SHALL the comparison be unavailable with no amounts, retaining the existing status and reason (for example `incomplete_period` with `unsupported_period_measurements`) and a `coverage` of zero covered slots. Actual metered costs SHALL remain available regardless of comparison availability.

#### Scenario: No battery
- **WHEN** system.has_battery is false
- **THEN** the cost-series comparison status is no_battery and the UI shows no battery comparison

#### Scenario: No recorded slots
- **WHEN** the period has no completed observations
- **THEN** comparison status is no_data with no amounts

#### Scenario: Strict calibration fails but an estimate is usable
- **WHEN** calibration is insufficient or fails a validation gate while the selected period has at least one usable run
- **THEN** the comparison returns estimate amounts with basis configured_losses and the original calibration state/reason
- **AND** the UI identifies the result as an estimate

#### Scenario: Partially covered period is never verified
- **WHEN** a valid calibration exists but some slots of the period are excluded
- **THEN** the comparison is an estimate with basis configured_losses and the calibration status/reason as the fit produced them
- **AND** coverage reports the covered and excluded slot counts

#### Scenario: No slot is estimate-eligible
- **WHEN** every slot of the period has invalid or unsupported measurements, prices, provenance or state-of-charge values
- **THEN** the comparison has no amounts, its coverage shows zero covered slots, and the UI shows a plain-language unavailable reason beside actual metered information

### Requirement: Self-use battery discharge excludes EV demand
The validated self-use simulation SHALL retain recorded EV energy in total grid demand while restricting battery discharge to the remaining non-EV deficit. Converted PV SHALL serve household/water demand first; its remainder SHALL be allowed to supply the EV. Mixed EV/household demand SHALL permit house-only discharge within calibrated losses and configured limits.

#### Scenario: EV-only demand with a full battery
- **WHEN** only an EV consumes 1 kWh, PV is zero and the battery is full
- **THEN** self-use discharges no battery energy and imports 1 kWh

#### Scenario: Mixed household and EV demand
- **WHEN** household/water demand is 0.4 kWh, EV demand is 1 kWh and PV is zero
- **THEN** self-use may discharge to cover the 0.4 kWh household/water demand
- **AND** all 1 kWh of EV energy remains grid import

#### Scenario: PV surplus supplies EV charging
- **WHEN** converted PV is 0.6 kWh, household/water demand is 0.4 kWh and EV demand is 1 kWh
- **THEN** 0.2 kWh PV supplies the EV and 0.8 kWh imports
- **AND** the battery does not discharge
