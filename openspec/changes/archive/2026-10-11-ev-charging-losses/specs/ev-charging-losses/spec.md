## ADDED Requirements

### Requirement: Per-charger EV loss settings
Each EV charger entry SHALL have the following settings:
- `charge_overhead_kw`: default 0.25. Allowed range 0–2.
- `start_loss_kwh`: default 0.15. Allowed range 0–1.
- `charge_efficiency`: default 0.95. Allowed range 0.5–1.0.
- `energy_added_sensor`: optional Home Assistant entity, default empty.

Existing configs SHALL receive the defaults through the config defaults merge. The config API SHALL reject values outside the ranges. The EV settings tab SHALL show the three numbers, each with a tooltip, and the sensor as an entity picker.

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
For each charger, Kepler SHALL count energy towards the goal as `charge_efficiency × wallbox energy − charge_overhead_kw × slot hours × charging-on − start_loss_kwh × start`, summed over eligible slots.

The "on" indicator SHALL cover both scheduled charging and surplus charging. A start SHALL be counted in any slot where the charger is on and was not on in the previous slot. For the first slot, the previous state SHALL be the charger's measured charging state at plan time. Grid import and the energy balance SHALL use the full wallbox energy. Each start SHALL also add `start_loss_kwh × import price` to the objective.

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
For every recorded slot with EV charger energy, the recorder SHALL also store car-side energy and its source next to the wallbox energy:
- `sensor`: the change of the charger's `energy_added_sensor` over the slot. If the sensor value drops during the slot (a session reset), the post-reset value SHALL count from zero.
- `soc`: when no sensor is configured, `ΔSoC / 100 × battery_capacity_kwh`, but only if SoC was fresh at both slot ends.
- Otherwise the value SHALL be NULL.

The database column SHALL be added by an automatic migration.

#### Scenario: Sensor reset mid-slot
- **WHEN** the energy-added sensor reads 24.8 at slot start, resets to 0 and reads 0.6 at slot end
- **THEN** the slot's car energy SHALL be 0.6 kWh with source `sensor`

#### Scenario: SoC fallback
- **WHEN** no sensor is configured, the battery capacity is 64 kWh, and fresh SoC goes from 60% to 62% during the slot
- **THEN** the slot's car energy SHALL be 1.28 kWh with source `soc`

#### Scenario: Stale SoC
- **WHEN** no sensor is configured and SoC is stale at either slot end
- **THEN** the slot's car energy SHALL be NULL

### Requirement: EV loss parameters are learned automatically
When `learning.reflex_enabled` is true, a daily job SHALL fit each charger's `charge_efficiency`, `charge_overhead_kw` and `start_loss_kwh`.

The fit SHALL use the last 30 days of slots with both wallbox and car energy, aggregated per charging day:
- Days with car/wall above 1.02 or below 0.3 SHALL be discarded.
- Sensor-sourced data SHALL be preferred, with SoC-sourced data used only when no sensor data exists.
- Parameters SHALL be updated only with at least 8 clean charging days and 20 starts.
- Results SHALL be clamped to overhead 0–1.0 kW, start loss 0–0.5 kWh and efficiency 0.80–1.00.
- Writes SHALL follow the existing Reflex daily max-change limits and SHALL be written into the charger's config entry.

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
