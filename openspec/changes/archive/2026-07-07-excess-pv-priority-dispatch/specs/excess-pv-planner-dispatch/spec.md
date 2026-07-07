## ADDED Requirements

### Requirement: Priority order allocates scarce surplus across multiple sinks

Excess-PV sinks SHALL be configured as an ordered list `executor.excess_pv.priority[]` of entries with `type` ∈ {`ev`, `water_heater_boost`, `custom_entity`}. The house battery always has implicit first priority via the SoC-threshold gate. The solver SHALL feed higher-priority sinks first when surplus is scarce by assigning each entry an effective reward of `boost_reward_sek_per_kwh × (1 − rank × 0.15)` (rank 0 = first), unless a per-entry `reward_sek_per_kwh` override is set. Multiple sinks MAY be active in the same slot when surplus covers them. An empty priority list SHALL disable excess-PV dispatch entirely.

#### Scenario: Scarce surplus goes to the highest-priority sink
- **WHEN** the priority list is [ev, water_heater_boost] and a slot's surplus covers only the EV minimum
- **THEN** the solver SHALL allocate the surplus to EV charging and SHALL NOT activate water heater boost in that slot

#### Scenario: Abundant surplus feeds multiple sinks
- **WHEN** a slot's surplus exceeds the EV maximum plus the water heater power
- **THEN** the solver MAY activate both the EV surplus and the water heater boost in that slot

#### Scenario: Empty priority list disables dispatch
- **WHEN** `excess_pv.priority` is an empty list
- **THEN** no sink variables SHALL be created and no sink actions SHALL be executed

#### Scenario: Reward override monotonicity warning
- **WHEN** a per-entry reward override gives a lower-priority sink a higher reward than a higher-priority sink
- **THEN** config validation SHALL emit a warning naming both entries

## MODIFIED Requirements

### Requirement: Sink activation requires configurable SoC threshold (default 95%)

Excess PV MUST always charge the battery first. Every sink in the priority list (EV surplus, water heater boost, custom entity) SHALL only activate in slots where the solver's projected battery SoC >= a configurable threshold `soc_threshold_percent` (default 95%). This is enforced via a big-M binary constraint in the MILP:

```
soc_binary[t] ∈ {0, 1}
soc[t] >= threshold_kWh - M * (1 - soc_binary[t])   // if binary=1, SoC >= threshold%
sink_var[t] <= soc_binary[t]                         // sink requires SoC above threshold
```

Where `M = capacity_kWh` and `threshold_kWh = capacity_kWh * soc_threshold_percent / 100`.

#### Scenario: Sink does not activate when battery is below threshold
- **WHEN** slot 14 has forecast excess PV (PV > load + water + EV)
- **AND** projected battery SoC in slot 14 is 80%
- **AND** `soc_threshold_percent` is 95
- **THEN** no sink in the priority list SHALL activate in slot 14
- **AND** the excess PV SHALL go to battery charging

#### Scenario: Sink activates when battery is at or above threshold
- **WHEN** slot 14 has forecast excess PV
- **AND** projected battery SoC in slot 14 is 95%
- **AND** `soc_threshold_percent` is 95
- **THEN** sinks MAY activate in slot 14 (subject to reward vs export economics and priority order)

#### Scenario: Lower threshold allows earlier sink activation
- **WHEN** `soc_threshold_percent` is set to 85
- **AND** projected battery SoC in slot 14 is 87%
- **THEN** sinks MAY activate in slot 14

#### Scenario: Battery charges first across the full horizon
- **WHEN** the solver plans a full day with morning low SoC and afternoon high PV
- **THEN** the solver SHALL schedule battery charging during morning/early afternoon
- **AND** sink activation SHALL only appear in slots where battery SoC first reaches the configured threshold
- **AND** no sink activation SHALL occur before the battery is near full

### Requirement: Kepler plans water heater boost with SoC gate

The Kepler solver SHALL schedule water heater boost (binary on/off per slot) only in slots where: (1) the pre-calculated excess PV flag is true, AND (2) projected SoC >= `soc_threshold_percent`. Boost variables SHALL be created only when a `water_heater_boost` entry exists in `excess_pv.priority[]`. No daily energy budget — the solver's energy balance naturally handles economics, and the executor's thermostat handles physics.

#### Scenario: Excess PV slot with full battery gets water heater boost
- **WHEN** slot 14 has forecast excess PV AND projected SoC >= 95%
- **AND** the priority list contains a `water_heater_boost` entry
- **THEN** the MILP SHALL create a boost binary variable for each water heater in that slot
- **AND** boost SHALL NOT appear in slots without forecast excess PV or with SoC < 95%

#### Scenario: No excess PV means no boost
- **WHEN** there are zero excess PV slots across the horizon
- **AND** the priority list contains a `water_heater_boost` entry
- **THEN** no boost slots appear in the schedule output

#### Scenario: Boost disabled when not in the priority list
- **WHEN** the priority list contains no `water_heater_boost` entry
- **THEN** no boost variables are created
- **AND** water heaters only get their normal minimum kWh

#### Scenario: Boost shares slot with normal heating
- **WHEN** a water heater already has normal heating scheduled in slot 14
- **AND** slot 14 has excess PV AND SoC >= 95%
- **THEN** the heater SHALL run continuously (already on) and the boost flag SHALL be set

### Requirement: Excess PV reward incentivizes solver over export (same for both sinks)

A configurable `boost_reward_sek_per_kwh` (default 0.5) SHALL be the base reward for all priority-list sinks, scaled per rank as defined by the priority-order requirement. For water heater boost, the reward is `effective_reward * boost_var * heater_kw * h`. For custom entity, the reward is `effective_reward * custom_entity_active_var * power_kw * h` where `power_kw` is configurable (default 1.0 kW). For EV surplus, the reward is `effective_reward * ev_surplus_kw * h`. Every sink's consumption SHALL be added to the energy-balance demand side, ensuring the solver makes genuine economic tradeoffs. Rewards are subtracted from the objective function, making the solver prefer sinks over export when the effective reward exceeds the export price.

#### Scenario: Boost activates when reward exceeds export price
- **WHEN** slot 14 has excess PV AND SoC >= 95%
- **AND** export price is 0.5 SEK/kWh
- **AND** the sink's effective reward is 1.0 SEK/kWh
- **THEN** the solver SHALL schedule that sink for the slot (sink earns more than exporting)

#### Scenario: Export wins when export price exceeds reward
- **WHEN** slot 14 has excess PV AND SoC >= 95%
- **AND** export price is 2.0 SEK/kWh
- **AND** the sink's effective reward is 1.0 SEK/kWh
- **THEN** the solver SHALL prefer exporting over the sink

### Requirement: Custom entity is a solver variable with reward and SoC gate

When the priority list contains a `custom_entity` entry, the solver SHALL create a binary variable `custom_entity_active[t]` per slot for that entry, constrained identically to water heater boost: (1) pre-calculated excess PV flag must be true, AND (2) projected SoC >= `soc_threshold_percent`. The reward is sized by the entry's configurable `power_kw` (default 1.0 kW). The custom entity's power consumption SHALL be added to the energy balance demand side: `custom_entity_active[t] * power_kw * h`. Multiple `custom_entity` entries MAY exist in the priority list, each with its own entity and variables. The executor toggles each entity based on the solver's decision, not pre-calculated flags.

#### Scenario: Custom entity activated by solver decision
- **WHEN** slot 14 has excess PV AND SoC >= 95%
- **AND** the priority list contains a `custom_entity` entry
- **AND** the effective reward exceeds the export price
- **THEN** the solver SHALL set `custom_entity_active[14] = 1`
- **AND** the schedule output SHALL include `custom_entity_active: true` for slot 14

#### Scenario: Custom entity NOT activated when battery is low
- **WHEN** slot 14 has excess PV but SoC is 70%
- **AND** the priority list contains a `custom_entity` entry
- **THEN** the solver SHALL set `custom_entity_active[14] = 0`
- **AND** the schedule output SHALL include `custom_entity_active: false` for slot 14

#### Scenario: Custom entity skipped when not in the priority list
- **WHEN** the priority list contains no `custom_entity` entry
- **THEN** no custom entity variables are created
- **AND** no custom entity actions are performed by the executor

### Requirement: Executor toggles custom entity based on schedule

The executor SHALL toggle each user-configured custom-entity sink on during slots where the schedule indicates `custom_entity_active: true` for it and off otherwise.

#### Scenario: Custom entity turned on during active slot
- **WHEN** the schedule has `custom_entity_active: true` in slot 14
- **AND** the priority list contains a `custom_entity` entry
- **WHEN** executor processes slot 14
- **THEN** the configured entity SHALL be set to `on_value`

#### Scenario: Custom entity turned off during inactive slot
- **WHEN** the schedule has `custom_entity_active: false` in slot 8
- **AND** the priority list contains a `custom_entity` entry
- **WHEN** executor processes slot 8
- **THEN** the configured entity SHALL be set to `off_value`

#### Scenario: Custom entity set to off_value on slot failure
- **WHEN** the executor enters `SLOT_FAILURE_FALLBACK`
- **AND** the priority list contains a `custom_entity` entry
- **THEN** the configured entity SHALL be set to `off_value`
- **AND** the entity SHALL NOT be left in an active state
