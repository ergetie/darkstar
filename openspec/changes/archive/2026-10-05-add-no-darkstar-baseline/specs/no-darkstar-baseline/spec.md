## ADDED Requirements

### Requirement: Baseline simulates a plain self-use inverter
The system SHALL compute a "without Darkstar" baseline by replaying the period's recorded slots through a plain self-use inverter with the same battery. For each slot, household demand SHALL be `load_kwh + water_kwh + ev_charging_kwh` and the surplus SHALL be `pv_kwh − demand`. A positive surplus SHALL charge the battery (up to the room below `battery.max_soc_percent` and up to `battery.max_charge_w` for the slot) and the remainder SHALL be exported. A deficit SHALL be covered by discharging the battery (down to `battery.min_soc_percent` and up to `battery.max_discharge_w` for the slot) and the remainder SHALL be imported. The baseline battery SHALL NOT charge from the grid and SHALL NOT export from the battery.

#### Scenario: PV surplus charges the battery first
- **WHEN** a slot has PV 1.0 kWh, demand 0.4 kWh and the battery has room
- **THEN** the baseline charges the battery with 0.6 kWh and exports nothing

#### Scenario: Surplus beyond the battery is exported
- **WHEN** a slot has a PV surplus larger than the battery's remaining room or charge limit
- **THEN** the battery takes only what fits and the rest is exported

#### Scenario: Deficit is covered by the battery
- **WHEN** a slot has demand above PV and the battery holds usable energy
- **THEN** the battery discharges to cover the deficit and the baseline imports only what the battery cannot cover

#### Scenario: Empty battery imports
- **WHEN** the simulated battery is at `min_soc_percent` and demand exceeds PV
- **THEN** the whole deficit is imported

#### Scenario: No grid charging and no battery export
- **WHEN** the price is very low or very high in a slot with no PV surplus or no deficit respectively
- **THEN** the baseline battery does not charge from the grid and does not export

### Requirement: Baseline battery accounting uses the configured limits and efficiencies
Stored energy SHALL change by `charge × battery.charge_efficiency` on charging and by `discharge ÷ battery.discharge_efficiency` on discharging, where the flows are the AC-side energy of the slot. Capacity SHALL be `battery.capacity_kwh`. Missing efficiencies SHALL default to 0.95 each, the same defaults the planner uses.

#### Scenario: Efficiency applied
- **WHEN** 1.0 kWh is charged with `charge_efficiency` 0.92
- **THEN** the simulated stored energy rises by 0.92 kWh

#### Scenario: Missing discharge efficiency
- **WHEN** `battery.discharge_efficiency` is not set
- **THEN** 0.95 is used

### Requirement: Baseline starts from the real state of charge at the start of the period
The simulated state of charge SHALL start at the `soc_end_percent` of the slot before the period's first slot; if absent, the first non-null `soc_end_percent` within the period; if none, `battery.min_soc_percent`. After the start the simulated state of charge SHALL be carried forward and SHALL NOT be re-synchronised to recorded values. Slots missing from the recorded data SHALL be skipped and SHALL leave the simulated state of charge unchanged. Slots SHALL be processed in chronological order, including across daylight-saving changes.

#### Scenario: Start from the previous slot's SoC
- **WHEN** the slot before the period has `soc_end_percent` 60
- **THEN** the simulation starts at 60 %

#### Scenario: No SoC recorded in the period
- **WHEN** no slot in or before the period has a SoC
- **THEN** the simulation starts at `battery.min_soc_percent`

#### Scenario: Recorded SoC does not steer the simulation
- **WHEN** the real battery was charged from the grid overnight
- **THEN** the simulated state of charge is unaffected by the real one

### Requirement: Baseline is priced and worn like the real figures
Baseline import cost SHALL be `import_kwh × import_price_sek_kwh` and export revenue `export_kwh × export_price_sek_kwh` using the slot's recorded prices (missing prices count as zero, as in the real figures). Baseline battery wear SHALL be `(charge_kwh + discharge_kwh) × battery_economics.battery_cycle_cost_kwh × 0.5` over the simulated flows. The saving SHALL be the baseline net cost including wear minus the real net cost including wear plus the value of the stored-energy difference defined by the requirement "Saving values the energy left in the battery at the end of the period".

#### Scenario: Same pricing as the real figures
- **WHEN** the baseline imports 2.0 kWh in a slot with import price 1.5
- **THEN** its import cost for the slot is 3.0

#### Scenario: Saving includes wear on both sides
- **WHEN** the baseline costs 40.0 kr incl. 1.0 kr wear, the real result is 30.0 kr incl. 2.0 kr wear and the stored-energy value is 0
- **THEN** the saving is 10.0 kr

### Requirement: Saving values the energy left in the battery at the end of the period
The system SHALL compute `stored_energy_difference_kwh` as the real end-of-period stored energy minus the simulated end-of-period stored energy, both as `soc_percent / 100 × battery.capacity_kwh`. The real end state of charge SHALL be the last non-null `soc_end_percent` of the period's started slots; the simulated end state of charge SHALL be the simulation's final state of charge (the start state of charge when there are no flows). The system SHALL compute `stored_energy_value_sek` as `stored_energy_difference_kwh × average import price × battery.discharge_efficiency`, where the average import price is the simple mean of `import_price_sek_kwh` over the period's started slots that have a price (0 when none have) and `battery.discharge_efficiency` defaults to 0.95. The value is positive when the real battery holds more energy than the baseline battery and negative when it holds less. When the period has no non-null real `soc_end_percent`, the difference and the value SHALL be unknown and SHALL count as 0 in the saving.

#### Scenario: Real battery holds more
- **WHEN** the real battery ends at 32 % and the baseline battery at 15 % of 27 kWh, the average import price is 2.54 and the discharge efficiency is 0.95
- **THEN** the difference is about 4.6 kWh and the value is about 11.1 kr in Darkstar's favour

#### Scenario: Real battery holds less
- **WHEN** the real battery ends at 30 % and the baseline battery at 50 % of 10 kWh at an average import price of 2.0 and efficiency 1.0
- **THEN** the difference is −2.0 kWh and the value is −4.0 kr

#### Scenario: Real end state of charge unknown
- **WHEN** no started slot of the period has a `soc_end_percent`
- **THEN** the difference and value are unknown and the saving is computed without them

#### Scenario: No import prices
- **WHEN** no started slot of the period has an import price
- **THEN** the average import price is 0 and the value is 0

### Requirement: Simulation exposes the final state of charge
The baseline simulation SHALL expose the simulated state of charge after the last slot in addition to the per-slot flows, without changing the per-slot flows.

#### Scenario: Final state of charge
- **WHEN** a 10 kWh battery starts at 50 %, charges 0.6 kWh and then discharges 1.0 kWh at efficiency 1.0
- **THEN** the simulated final state of charge is 46 %

### Requirement: Baseline is unavailable without a battery
When `system.has_battery` is false the baseline SHALL NOT be computed or shown. When the period has no recorded slots there SHALL be no baseline.

#### Scenario: No battery
- **WHEN** `system.has_battery` is false
- **THEN** the cost series carries no baseline and the UI shows no comparison

#### Scenario: No recorded slots
- **WHEN** the period has no started slots
- **THEN** there is no baseline
