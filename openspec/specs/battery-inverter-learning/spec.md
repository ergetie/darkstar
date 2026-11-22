# battery-inverter-learning Specification

## Purpose
Defines how Darkstar measures battery round-trip efficiency and inverter charge-path losses from recorded data, how the planner's effective efficiencies are composed from them, and which battery facts are only monitored with warnings.

## Requirements

### Requirement: Round-trip efficiency is measured from contiguous runs with a SoC correction
Battery round-trip efficiency (RTE) SHALL be estimated from the DC-side battery counters pooled over every run of back-to-back eligible slots of at least one day, corrected for the net SoC change of the pool (`change = dSoC x configured capacity`, symmetric split: `charge x sqrt(RTE) - discharge / sqrt(RTE) = change`), so that a SoC-neutral pool gives total discharge divided by total charge. A run's first slot SHALL only supply the starting SoC.

#### Scenario: Pooled estimate
- **WHEN** eligible runs cover 35 days with a discharge of 800 kWh and a charge of 832 kWh and the battery ends where it started
- **THEN** the RTE estimate is about 0.962

#### Scenario: Days are not SoC-neutral
- **WHEN** the SoC swings by 40 percentage points over every week but the true RTE is 0.962
- **THEN** the corrected estimate is within 0.002 of 0.962

#### Scenario: Net SoC drift is corrected
- **WHEN** the battery gains 15 kWh of stored energy over the pool
- **THEN** the estimate accounts for it and is not the plain discharge-over-charge ratio

### Requirement: RTE runs need no alignment and the pool is gated
Runs SHALL NOT need to align to local days or midnight, and a gap or unusable slot SHALL only end the run it is in. The pool SHALL cover at least 28 days and 5 times the configured capacity in discharge, and the SoC correction SHALL NOT exceed 10 % of the charged energy, otherwise no value is stored.

#### Scenario: Not enough days
- **WHEN** eligible runs cover 20 days
- **THEN** no RTE value is stored and the evidence reports the shortfall

#### Scenario: Correction too large
- **WHEN** the net SoC change times the configured capacity exceeds 10 % of the charged energy
- **THEN** no value is stored and the reason names the net charge change

#### Scenario: Gaps in recorded data
- **WHEN** one slot per week is unusable and a few slots are missing
- **THEN** only the affected runs are cut, all other runs are pooled and the estimate is unchanged

### Requirement: RTE uses only recorded, trustworthy battery slots
A slot SHALL be used for RTE only if its battery charge, battery discharge and SoC values are all present, its battery and SoC provenance is a measured (power-history, live) recording, it is not marked `exclude`, and it lies in the past. Missing values SHALL never be treated as zero. A run SHALL end at any unusable slot.

#### Scenario: Null battery value
- **WHEN** a slot has a null battery discharge
- **THEN** the run is cut there and the null is not counted as 0 kWh

#### Scenario: Excluded slot
- **WHEN** a slot carries the `exclude` flag
- **THEN** the run is cut there

### Requirement: Inverter loss is the energy-balance residual
A slot's inverter loss SHALL be `(pv + import + battery discharge) - (load + ev + water + export + battery charge)`. The estimator SHALL fit it, outlier-robustly, as standby power times slot hours plus a fraction `k` of the DC battery charge energy, over eligible slots only (clean recording, not `exclude`, no base-load integrity flag, no nulls, in the past). The stored charge loss SHALL be AC-side: `k / (1 + k)`.

#### Scenario: Recovered model
- **WHEN** reliable slots are generated with 60 W standby and a loss of 7.5 % of DC charge energy plus noise and a few outliers
- **THEN** the fit returns a standby within 10 W and a stored AC-side charge loss within 0.01 of 0.0698 (0.075 / 1.075)

#### Scenario: Unreliable slots skipped
- **WHEN** a slot has `base_load.reliable` false or an unmeasured device component
- **THEN** it does not enter the fit

#### Scenario: Data gate
- **WHEN** fewer than 1000 reliable slots spanning 14 days exist, or their battery charge is below 2 times the configured capacity
- **THEN** no inverter loss value is stored

### Requirement: A configured inverter-loss sensor can replace the balance
When `input_sensors.inverter_power_losses` is configured, the recorder SHALL integrate it per slot into a separate table of per-slot loss energy (null when the sensor was unavailable, never zero), and the inverter-loss estimator SHALL use these values instead of the balance residual for slots that have one. Without the sensor the balance is used.

#### Scenario: Sensor configured
- **WHEN** the sensor is configured and a slot has a recorded loss of 0.04 kWh
- **THEN** the estimator uses 0.04 kWh for that slot

#### Scenario: Sensor unavailable for a slot
- **WHEN** the sensor was unavailable during a slot
- **THEN** no loss row is written and the slot falls back to the balance residual

### Requirement: Standby power is informational
The measured inverter standby power SHALL be stored and shown with its evidence but SHALL NOT change any planning input, because a constant draw does not change which schedule is optimal.

#### Scenario: Planning unaffected
- **WHEN** a standby value is learned
- **THEN** the planner's inputs and the Kepler configuration are identical to those without it

### Requirement: Stored values state which side of the inverter they describe
RTE SHALL refer to the battery terminals (DC in, DC out). `inverter_charge_loss` SHALL be the fraction of AC-side charge energy lost before the DC side (DC charge = AC charge x (1 - loss)). `inverter_discharge_efficiency` SHALL be the DC-to-AC efficiency (AC out = DC out x efficiency). The planner's charge and discharge variables are AC-side, so the DC-side counters SHALL never be combined with the planner's effective efficiencies.

#### Scenario: Known truth reproduced
- **GIVEN** true RTE 0.96, AC-side charge loss 0.07 and discharge efficiency 0.97
- **WHEN** AC-side flows are rolled through the composed efficiencies
- **THEN** the stored energy equals the true DC-side stored energy

### Requirement: Effective planner efficiencies are composed from the parts
When round-trip efficiency, inverter charge loss and inverter discharge efficiency are all available (learned and valid, or locked, or the default for discharge), the planner SHALL use `charge_efficiency = (1 - inverter_charge_loss) x sqrt(RTE)` and `discharge_efficiency = sqrt(RTE) x inverter_discharge_efficiency`. Otherwise it SHALL use `battery.charge_efficiency` and `battery.discharge_efficiency` from config for both. The same values SHALL feed Kepler, the price reserve and the benchmark.

#### Scenario: Composition
- **WHEN** RTE is 0.962, charge loss 0.075 and discharge efficiency 0.97
- **THEN** charge efficiency is about 0.907 and discharge efficiency about 0.951

#### Scenario: Partial data falls back
- **WHEN** RTE is learned but no valid charge loss exists
- **THEN** both efficiencies come from config

#### Scenario: Config not modified
- **WHEN** effective values are used
- **THEN** `battery.charge_efficiency` and `battery.discharge_efficiency` in config are unchanged

### Requirement: Inverter discharge efficiency is not measured
The inverter discharge efficiency SHALL default to 0.97, SHALL have no estimator, and SHALL be changeable only by the user lock (bounds 0.85 to 1.0).

#### Scenario: Default
- **WHEN** the user has not locked it
- **THEN** its source is `default` and its value 0.97

### Requirement: Capacity changes only warn
The system SHALL compute implied battery capacity per 7-day window from recorded flows and SoC (window SoC range of at least 20 percentage points) and SHALL raise a health warning when the two latest consecutive windows each differ from the median of the preceding 8 windows by at least 25 %, with at least 4 valid baseline windows. It SHALL NOT change any setting or planning input.

#### Scenario: Module outage
- **WHEN** the baseline is 34 kWh and the two latest windows read 19 kWh
- **THEN** a capacity-change warning is shown with both values

#### Scenario: Seasonal shift
- **WHEN** the latest windows read 20 % above the baseline
- **THEN** no warning is raised

#### Scenario: Never applied
- **WHEN** the warning is active
- **THEN** `battery.capacity_kwh` and the planner's capacity are unchanged

### Requirement: Low delivered battery power only warns
The system SHALL raise a health warning when, over the last 14 days and at least 20 slots where the plan asked for at least 95 % of the configured maximum charge (or discharge) power, the median recorded battery power is below 80 % of the planned power. It SHALL NOT change any setting or planning input.

#### Scenario: Battery under-delivers
- **WHEN** 30 slots planned at 5.0 kW were recorded at a median 3.5 kW
- **THEN** a warning names the planned and delivered power

#### Scenario: Too few slots
- **WHEN** fewer than 20 qualifying slots exist
- **THEN** no warning is raised
