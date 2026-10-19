# Spec: EV Charging Losses

## Purpose

Models EV charging losses (efficiency, overhead, start loss) in planning, records car-side energy, and learns the parameters.

## Requirements
### Requirement: Per-charger EV loss settings
Each EV charger entry SHALL have the settings `charge_overhead_kw`, `start_loss_kwh`, `charge_efficiency` and an optional `energy_added_sensor`. Existing configs SHALL receive the defaults through the config defaults merge, and the config API SHALL reject values outside the allowed ranges.

#### Scenario: Setting defaults and ranges
- **WHEN** a charger entry is configured
- **THEN** `charge_overhead_kw` defaults to 0.25 with allowed range 0–2
- **AND** `start_loss_kwh` defaults to 0.15 with allowed range 0–1
- **AND** `charge_efficiency` defaults to 0.95 with allowed range 0.5–1.0
- **AND** `energy_added_sensor` is an optional Home Assistant entity, default empty

#### Scenario: Settings UI
- **WHEN** the EV settings tab is shown
- **THEN** it shows the three numbers, each with a tooltip, and the sensor as an entity picker

#### Scenario: Existing config gets defaults
- **WHEN** a user upgrades with an EV charger entry that has none of the new keys
- **THEN** the charger SHALL use overhead 0.25 kW, start loss 0.15 kWh and efficiency 0.95

#### Scenario: Out-of-range value rejected
- **WHEN** a user saves `charge_efficiency: 1.2`
- **THEN** the config API SHALL reject the save with a validation error naming the field

#### Scenario: Settings visible in the EV tab
- **WHEN** the user opens an EV charger in the EV settings tab
- **THEN** the overhead, start loss and efficiency fields and the energy-added sensor picker SHALL be shown with their current values

### Requirement: Kepler credits EV goals after charging losses
For each charger, Kepler SHALL count energy towards the goal as `charge_efficiency × wallbox energy − charge_overhead_kw × slot hours × charging-on − start_loss_kwh × start`, summed over eligible slots. Grid import and the energy balance SHALL use the full wallbox energy.

#### Scenario: On indicator and starts
- **WHEN** Kepler evaluates a slot
- **THEN** the "on" indicator covers both scheduled charging and surplus charging
- **AND** a start is counted in any slot where the charger is on and was not on in the previous slot
- **AND** for the first slot, the previous state is the charger's measured charging state at plan time

#### Scenario: Start cost in objective
- **WHEN** a start occurs
- **THEN** `start_loss_kwh × import price` is added to the objective

#### Scenario: Fewer high-power slots preferred
- **WHEN** a goal of 10 kWh can be met either by four slots at 2.3 kW or by one and a half hours at 7 kW at equal prices
- **THEN** the plan SHALL choose the higher-power, fewer-slot option

#### Scenario: Loss raises energy needed from the grid
- **WHEN** the requirement is 10 kWh with efficiency 0.95 and no overhead or start loss
- **THEN** the plan SHALL schedule at least 10.53 kWh of wallbox energy

#### Scenario: Continuing a running session costs no start
- **WHEN** the charger is charging at plan time and the plan keeps it on in the first slot
- **THEN** no start loss SHALL be counted for that slot

#### Scenario: Surplus charging pays the overhead
- **WHEN** a charger absorbs surplus PV in a slot
- **THEN** that slot SHALL count as charging-on and the overhead SHALL be deducted from its goal credit

### Requirement: Car-side energy is recorded per slot
For every recorded slot with EV charger energy, the recorder SHALL also store car-side energy and its source next to the wallbox energy, from the charger's `energy_added_sensor` when configured, otherwise from SoC change, otherwise NULL. The database column SHALL be added by an automatic migration.

#### Scenario: Sensor-sourced car energy
- **WHEN** the charger has an `energy_added_sensor`
- **THEN** the source is `sensor`, the change of the sensor over the slot
- **AND** a drop in the sensor value counts as a session reset (post-reset value counts from zero) only when the new value is at or below a configurable near-zero threshold (default 0.5 kWh)
- **AND** any other drop contributes 0 kWh (sensor drift)

#### Scenario: SoC-sourced car energy
- **WHEN** no sensor is configured and SoC was fresh at both slot ends
- **THEN** the source is `soc`, with value `ΔSoC / 100 × battery_capacity_kwh`
- **AND** otherwise the value is NULL

#### Scenario: Validation bounds
- **WHEN** car energy is derived from the sensor
- **THEN** it does not exceed the slot's wallbox energy plus a tolerance, and is 0 when wallbox energy is approximately zero
- **AND** when the aggregate EV energy for a slot is rejected by validation, the stored car energy is zeroed together with the per-charger wallbox energy

#### Scenario: Sensor reset mid-slot
- **WHEN** the energy-added sensor reads 24.8 at slot start, resets to 0 and reads 0.6 at slot end, and the wallbox delivered at least 0.6 kWh
- **THEN** the slot's car energy SHALL be 0.6 kWh with source `sensor`

#### Scenario: Idle sensor drift
- **WHEN** the sensor reads 22.47, 22.36, 22.25 over idle slots with wallbox energy 7.5e-05 kWh per slot
- **THEN** each slot's car energy SHALL be 0 kWh

#### Scenario: Non-zero drop
- **WHEN** the sensor drops from 22.4 to 3.0 (not near zero) and then rises to 3.8 with wallbox energy 1.0 kWh
- **THEN** the drop SHALL contribute 0 and the 0.8 kWh rise SHALL count, capped by wallbox energy plus tolerance

#### Scenario: Car energy exceeds wallbox energy
- **WHEN** the sensor change is 2.0 kWh but wallbox energy is 1.0 kWh
- **THEN** car energy SHALL be capped to 1.0 kWh plus tolerance

#### Scenario: Rejected aggregate
- **WHEN** the slot's aggregate EV energy is rejected and zeroed
- **THEN** per-charger car energy SHALL also be zeroed

#### Scenario: SoC fallback
- **WHEN** no sensor is configured, the battery capacity is 64 kWh, and fresh SoC goes from 60% to 62% during the slot
- **THEN** the slot's car energy SHALL be 1.28 kWh with source `soc`

#### Scenario: Stale SoC
- **WHEN** no sensor is configured and SoC is stale at either slot end
- **THEN** the slot's car energy SHALL be NULL

### Requirement: EV loss parameters are learned automatically
When `learning.reflex_enabled` is true, a daily job SHALL fit each charger's `charge_efficiency`, `charge_overhead_kw` and `start_loss_kwh` from the last 30 days of slots with both wallbox and car energy, aggregated per charging day.

#### Scenario: Data selection
- **WHEN** the daily job fits parameters
- **THEN** days with car/wall above 1.02 or below 0.3 are discarded
- **AND** sensor-sourced data is preferred, with SoC-sourced data used only when no sensor data exists

#### Scenario: Update thresholds and limits
- **WHEN** the fit completes
- **THEN** parameters are updated only with at least 8 clean charging days and 20 starts
- **AND** results are clamped to overhead 0–1.0 kW, start loss 0–0.5 kWh and efficiency 0.80–1.00
- **AND** writes follow the existing Reflex daily max-change limits and are written into the charger's config entry

#### Scenario: Not enough data
- **WHEN** a charger has 5 clean charging days in the last 30 days
- **THEN** its loss parameters SHALL NOT change

#### Scenario: Learned values appear in settings
- **WHEN** the job fits overhead 0.31 kW with enough data and the daily max change allows it
- **THEN** the charger's `charge_overhead_kw` in config SHALL move towards 0.31, and the EV tab SHALL show the new value

#### Scenario: Learning disabled
- **WHEN** `learning.reflex_enabled` is false
- **THEN** no EV loss parameter SHALL be changed

### Requirement: Goal accounting uses car-side energy
When SoC is unavailable and required energy falls back to delivered energy, delivered energy SHALL be the recorded car energy where present, else wallbox energy × `charge_efficiency`. Goal diagnostics and progress SHALL use the same rule.

#### Scenario: Fallback without SoC
- **WHEN** SoC is unavailable, 10 kWh of wallbox energy was recorded today without car energy, and efficiency is 0.9
- **THEN** 9 kWh SHALL be counted as delivered towards the goal
