# ev-charging-power Specification

## Purpose
TBD - created by archiving change ev-planning-model. Update Purpose after archive.
## Requirements
### Requirement: Charger power limits are derived from electrical configuration
A single shared helper SHALL compute each charger's power limits:
- **`type: current` chargers:**
  - `max_kw = max_current_a × len(phases) × V / 1000`;
  - `min_kw = min_current_a × len(phases) × V / 1000 × 1.01`;
  - `V` is `system.grid.nominal_voltage_v`, default 230.
- **`type: binary` chargers:** `max_kw = min_kw = rated_power_kw`. Voltage, amps and phases SHALL NOT affect a binary charger's limits.

The planner adapter, pipeline status and diagnostics helpers, preflight, load registration service, and executor kW↔A conversion SHALL all use this helper. No consumer SHALL read `max_power_kw` for EV chargers.

#### Scenario: 10 A three-phase current charger
- **WHEN** a current charger has `max_current_a: 10`, `min_current_a: 6`, `phases: [1,2,3]`, and nominal voltage 230
- **THEN** `max_kw` SHALL be 6.9 and `min_kw` SHALL be about 4.18

#### Scenario: Binary charger
- **WHEN** a binary charger has `rated_power_kw: 3.7`
- **THEN** both limits SHALL be 3.7 kW

#### Scenario: Binary charger ignores voltage
- **WHEN** a binary charger has `rated_power_kw: 3.7` and the nominal voltage is 120, 230 or 240
- **THEN** both limits SHALL be 3.7 kW

#### Scenario: Executor uses the same voltage
- **WHEN** nominal voltage is configured as 240
- **THEN** the executor's planned-kW-to-amps conversion SHALL divide by `240 × active_phases`

### Requirement: Legacy max_power_kw is migrated
Config migration SHALL:
- remove `max_power_kw` and `nominal_power_kw` from `type: current` charger entries, logging the derived `max_kw`;
- rename `max_power_kw`, or `nominal_power_kw` when `max_power_kw` is absent, to `rated_power_kw` on `type: binary` entries.

Migration SHALL be idempotent and SHALL preserve a pre-migration config backup.

#### Scenario: Prod current charger
- **WHEN** a current charger has `max_power_kw: 11`, `nominal_power_kw: 11`, `max_current_a: 12`, and 3 phases
- **THEN** both kW keys SHALL be removed
- **AND** the migration log SHALL report a derived maximum of about 8.3 kW

#### Scenario: Binary charger
- **WHEN** a binary charger has `max_power_kw: 3.7`
- **THEN** the migrated entry SHALL have `rated_power_kw: 3.7` and no `max_power_kw`

#### Scenario: Re-running migration
- **WHEN** migration runs on an already-migrated config
- **THEN** the config SHALL be unchanged

### Requirement: Charger editor shows derived power read-only
The settings charger editor SHALL NOT offer a free-typed max-power field for current chargers. It SHALL display the derived maximum and minimum kW read-only, updating live as amps and phases change. For binary chargers it SHALL offer `rated_power_kw`.

#### Scenario: Editing amps updates derived power
- **WHEN** the user changes `max_current_a` from 12 to 10 on a 3-phase charger
- **THEN** the displayed maximum SHALL change from 8.3 kW to 6.9 kW

### Requirement: Single nominal grid voltage
The system SHALL have one nominal grid voltage, `system.grid.nominal_voltage_v` (default 230 V, the EU standard), configured next to `system.grid.main_fuse_a`. Every kW↔A conversion SHALL use it:
- EV charger power derivation (shared helper);
- executor planned-kW-to-amps, manual-charge power, measured-draw and per-phase W→A conversion;
- excess-PV surplus amps and the 1-/3-phase minimum-power thresholds;
- the load balancer's power-mode phase conversion when that phase has no `input_sensors.grid_voltage_l*` entity. A configured per-phase voltage sensor SHALL take precedence for real-time control.

No code path SHALL hard-code a grid voltage. Config validation SHALL reject a value outside 100–260 V. The settings page SHALL show the field in the System profile next to the grid limits.

#### Scenario: Default voltage
- **WHEN** `system.grid.nominal_voltage_v` is unset
- **THEN** every conversion SHALL use 230 V

#### Scenario: Per-phase sensor wins in the load balancer
- **WHEN** L1 reports power and `input_sensors.grid_voltage_l1` reads 236 V
- **THEN** the balancer SHALL convert L1 using 236 V, not the nominal voltage

#### Scenario: Out-of-range voltage rejected
- **WHEN** the user saves `system.grid.nominal_voltage_v: 400`
- **THEN** validation SHALL return an error

### Requirement: Legacy load-balancing voltage is migrated
Config migration SHALL move `load_balancing.nominal_voltage_v` to `system.grid.nominal_voltage_v` (inserted after `main_fuse_a` when present) and remove the old key. When the new key already exists, it SHALL win and the old key SHALL be removed. The migration SHALL run before the charger-power migration, be idempotent, and use the existing backup-before-write mechanism.

#### Scenario: Legacy value moved
- **WHEN** a config has `load_balancing.nominal_voltage_v: 225` and no `system.grid.nominal_voltage_v`
- **THEN** the migrated config SHALL have `system.grid.nominal_voltage_v: 225` and no `load_balancing.nominal_voltage_v`
- **AND** a timestamped backup of the pre-migration config SHALL exist

#### Scenario: Re-running voltage migration
- **WHEN** migration runs on an already-migrated config
- **THEN** the config SHALL be unchanged

### Requirement: A current charger without phases is disabled visibly
A `type: current` charger with no `phases` SHALL stay disabled for planning, but SHALL never be silent:
- the load registration service SHALL register it with `disabled_reason: missing_phases` and log a warning;
- `GET /api/ev/chargers` SHALL still list it, with a `disabled_reason` message naming the charger by its configured `name` (falling back to `id`), e.g. "Configure phases for <name> to enable planning"; the message SHALL never hard-code a charger brand;
- the EV card SHALL show that message;
- config migration SHALL log a warning for each such charger;
- in the settings charger editor, phases SHALL be a required field for current chargers, pre-filled with L1/L2/L3 for new chargers, and saving a current charger without phases SHALL be blocked with the same message.

#### Scenario: Charger missing phases
- **WHEN** a current charger named "Garage" has `max_current_a: 12` and no `phases`
- **THEN** the EV card SHALL show "Configure phases for Garage to enable planning"
- **AND** the planner SHALL not schedule it

#### Scenario: New charger
- **WHEN** the user adds a new EV charger in settings
- **THEN** its phases SHALL be pre-filled with L1, L2 and L3
