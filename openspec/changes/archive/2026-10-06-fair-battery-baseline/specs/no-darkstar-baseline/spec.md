## MODIFIED Requirements

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
For the validated comparison, stored energy SHALL change by `charge * eta_charge` and `discharge / eta_discharge`, using calibrated effective factors in the recorded flow boundary. Capacity SHALL be configured `battery.capacity_kwh`. Configured minimum/maximum SoC and separate charge/discharge power limits SHALL be enforced. Missing or unreliable calibration SHALL make the comparison unavailable; planner/default efficiencies SHALL NOT be substituted as a learned comparison model. Inverter conversion and battery storage losses SHALL each be applied once.

#### Scenario: Efficiency applied
- **WHEN** 1.0 kWh is charged with validated `eta_charge` 0.92
- **THEN** simulated stored energy increases by 0.92 kWh

#### Scenario: Missing discharge calibration
- **WHEN** the discharge factor cannot be reliably calibrated
- **THEN** the validated comparison is unavailable rather than defaulting to 0.95

#### Scenario: Separate limits
- **WHEN** configured charge power is lower than discharge power
- **THEN** charging and discharging respect their respective limits

### Requirement: Baseline starts from the real state of charge at the start of the period
The validated simulation SHALL start from the first completed slot's valid `soc_start_percent`, otherwise from the immediately preceding contiguous slot's valid `soc_end_percent`. Both comparison sides SHALL use that common starting energy. A later slot's SoC, the first slot's end SoC, or minimum configured SoC SHALL NOT substitute for missing starting measurements. The simulated state SHALL be carried forward without resynchronizing to later real SoC. Comparison observations SHALL be processed in UTC chronological order across DST. Missing completed slots or invalid essential observations within the selected observed period SHALL make the comparison unavailable; the currently incomplete slot SHALL be excluded and the comparison through-time SHALL be exposed.

#### Scenario: Start from the previous slot's SoC
- **WHEN** the first slot has no start SoC and the immediately preceding slot ends at 60%
- **THEN** the simulation starts at 60%

#### Scenario: No starting SoC
- **WHEN** there is no measured SoC at the selected period's start
- **THEN** the comparison is unavailable with `incomplete_period`

#### Scenario: Recorded SoC does not steer the simulation
- **WHEN** the real battery charges from the grid overnight
- **THEN** the later real SoC does not reset the self-use simulation

#### Scenario: Missing interior observation
- **WHEN** a completed 15-minute slot is absent inside the comparison period
- **THEN** the comparison is unavailable instead of silently skipping that demand

#### Scenario: DST transition
- **WHEN** the clock repeats or skips a local hour
- **THEN** observations and adjacent-slot checks use elapsed UTC time

### Requirement: Baseline is priced and worn like the real figures
Both validated comparison sides SHALL use the same calibrated grid model and slot prices. The Darkstar side SHALL supply recorded battery actions; self-use SHALL supply simulated battery actions. Both SHALL price non-negative import/export derived from modeled net grid energy, without adding gross metered overlap to one side alone. Missing essential prices SHALL make the comparison unavailable. Metered gross import/export costs SHALL remain available separately as actual electricity costs.

Each side's wear SHALL be `(charge_kwh + discharge_kwh) * battery_economics.battery_cycle_cost_kwh * 0.5`. Its comparison cost SHALL equal modeled grid cost plus wear minus the value of stored-energy change from the common start. Estimated saving SHALL equal self-use comparison cost minus Darkstar comparison cost. This SHALL be identified as a 15-minute battery-management estimate; exact sub-slot inverter responses SHALL NOT be asserted or compensated with an arbitrary penalty.

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

### Requirement: Saving values the energy left in the battery at the end of the period
Both comparison sides SHALL value their stored-energy change from the common start using the same reference price: the mean recorded import price of the completed comparison slots multiplied by validated `eta_out * eta_discharge`. Darkstar end energy SHALL come from the final completed slot's measured SoC; self-use end energy SHALL come from its simulation. Stored-energy difference SHALL remain real end energy minus simulated end energy. The difference in stored-energy value SHALL contribute positively to saving when Darkstar retains more energy at a positive reference price and negatively when it retains less. Missing end SoC or prices SHALL withhold the validated comparison, not count the missing adjustment as zero. Valid zero and negative prices SHALL retain their values.

#### Scenario: Real battery holds more
- **WHEN** Darkstar retains 4.6 kWh more than self-use and reference price after conversion losses is 2.4 kr/kWh
- **THEN** stored-energy difference adds 11.04 kr to estimated saving

#### Scenario: Real battery holds less
- **WHEN** Darkstar retains 2.0 kWh less and reference price is 2.0 kr/kWh
- **THEN** stored-energy difference subtracts 4.0 kr from estimated saving

#### Scenario: Real end state of charge unknown
- **WHEN** the final completed comparison slot has no valid real end SoC
- **THEN** the validated comparison is unavailable

#### Scenario: No import prices
- **WHEN** essential import prices are missing
- **THEN** the validated comparison is unavailable rather than valuing unknown energy at zero

#### Scenario: Negative valuation
- **WHEN** the mean import price is negative
- **THEN** the stored-energy reference price remains negative and is explained as a valuation assumption

### Requirement: Baseline is unavailable without a battery
When `system.has_battery` is false, no battery comparison SHALL be computed or shown. Empty periods SHALL have no comparison amounts. Insufficient calibration, failed validation or incomplete selected-period observations SHALL expose an explicit unavailable status and no estimated saving. Actual metered costs SHALL remain available regardless of comparison availability.

#### Scenario: No battery
- **WHEN** `system.has_battery` is false
- **THEN** the cost-series comparison status is `no_battery` and the UI shows no battery comparison

#### Scenario: No recorded slots
- **WHEN** the period has no completed observations
- **THEN** comparison status is `no_data` with no amounts

#### Scenario: Unreliable data
- **WHEN** calibration or selected-period validation fails
- **THEN** the UI presents a plain-language unavailable reason alongside actual metered information


## ADDED Requirements

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
