## Purpose

Define which recorded PV slots are trustworthy training and bias-measurement samples, so the model learns shading and zero production, and does not learn from sensor dropouts, spikes or curtailed output.

## ADDED Requirements

### Requirement: Zero-production slots with a positive baseline are kept
PV training SHALL include every slot whose Open-Meteo baseline is greater than 0.01 kWh, including slots where recorded PV is 0, so the model can learn shaded periods.

#### Scenario: Shaded morning
- **WHEN** a slot has baseline 0.20 kWh and recorded PV 0.00 kWh and passes the other rules
- **THEN** the slot SHALL be used for training with residual -0.20 kWh

#### Scenario: Night
- **WHEN** a slot has baseline 0.01 kWh or less and recorded PV 0
- **THEN** the slot SHALL NOT be used for training

### Requirement: Implausible PV slots are dropped
PV training SHALL drop slots that are not credible measurements: dropouts (recorded PV 0 while baseline exceeds 0.3 kWh), spikes (recorded PV above 1.05 times the total configured array kWp times 0.25 h, or above 0.05 kWh while the sun is more than 3 degrees below the horizon), and curtailed slots (battery SoC at or above 97 %, export below 0.02 kWh and baseline above 0.05 kWh). Rules needing a missing input (kWp, SoC, export, location) SHALL be skipped for that slot.

#### Scenario: Inverter dropout
- **WHEN** a slot has recorded PV 0 and baseline 0.45 kWh
- **THEN** it SHALL be dropped

#### Scenario: Spike above array capacity
- **WHEN** total array capacity is 10 kWp and a slot records 2.8 kWh (limit 2.625 kWh)
- **THEN** it SHALL be dropped

#### Scenario: Production at night
- **WHEN** a slot records 0.10 kWh with the sun 10 degrees below the horizon
- **THEN** it SHALL be dropped

#### Scenario: Curtailed by full battery
- **WHEN** SoC is 100 %, export is 0.00 kWh and baseline is 0.40 kWh
- **THEN** it SHALL be dropped, because recorded PV understates what the panels could produce

#### Scenario: SoC or export unavailable
- **WHEN** the SoC or export value of a slot is missing
- **THEN** the curtailment rule SHALL NOT drop that slot

#### Scenario: Forecast too high or too low
- **WHEN** a slot is a genuine measurement, whether recorded PV is far below or far above the baseline (and within capacity)
- **THEN** it SHALL be kept, so the model learns both over- and under-forecasting

### Requirement: The same cleaning applies to the Reflex bias input
The PV forecast-vs-actual data used by Reflex SHALL use exactly the same inclusion and drop rules as PV training.

#### Scenario: Curtailed day
- **WHEN** the battery was full and exports were zero for part of a day
- **THEN** those slots SHALL be excluded from the bias measurement as well as from training

#### Scenario: Load comparison unaffected
- **WHEN** forecast-vs-actual data is requested for load
- **THEN** PV cleaning SHALL NOT be applied
