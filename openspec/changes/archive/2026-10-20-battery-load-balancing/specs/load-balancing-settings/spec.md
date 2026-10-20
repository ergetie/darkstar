## ADDED Requirements

### Requirement: Battery give-way kind in configuration
`load_balancing.give_way_order` SHALL accept entries with `kind: battery` in addition to `charger` and `shed`. There SHALL be at most one battery entry, and its id SHALL be normalised to `battery`. Duplicates SHALL be dropped with a warning.

#### Scenario: Battery entry parsed
- **WHEN** the config lists `{kind: battery, id: battery}` between a charger and a shed load
- **THEN** the parsed order SHALL keep the battery at that position

### Requirement: Battery entry self-heal
`heal_give_way_order` SHALL keep a battery entry only while a controllable battery exists, meaning a loaded inverter profile with a `charge` mode. Otherwise it SHALL drop the entry with a warning. When a controllable battery exists and no battery entry is listed, it SHALL append one at the end of the list. The frontend display heal SHALL mirror this rule.

#### Scenario: Existing user upgrades
- **WHEN** a config with only charger and shed entries is loaded and a Deye profile is active
- **THEN** a battery entry SHALL be appended after the last entry

#### Scenario: No inverter profile
- **WHEN** no inverter profile is loaded
- **THEN** any battery entry SHALL be dropped from the effective order

### Requirement: Battery shown in settings order and live status
The load-balancing settings give-way editor SHALL show the battery entry as "House battery (grid charging)" and SHALL let the user move it like any other entry. The load-balancer status API SHALL include a `battery` object with planned power, capped power, state (`idle`, `throttling`, `paused`) and reason. The status card SHALL render it using the design-system tokens.

#### Scenario: Throttled battery visible
- **WHEN** the balancer caps battery grid charging from 10 kW to 7 kW
- **THEN** the status API and card SHALL show the battery as throttling with 10 kW planned and 7 kW capped
