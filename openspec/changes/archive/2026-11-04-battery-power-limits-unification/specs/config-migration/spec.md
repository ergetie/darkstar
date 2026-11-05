## ADDED Requirements

### Requirement: Remove stray battery kW limit keys
Startup migration SHALL drop `battery.max_charge_power_kw` and `battery.max_discharge_power_kw` from the user's config when present, log each removal, and leave all other keys (including `max_charge_a`, `max_discharge_a`, `max_charge_w`, `max_discharge_w`) untouched. The migration SHALL be idempotent.

#### Scenario: Old config
- **WHEN** a config contains `battery.max_charge_power_kw: 8` and `battery.max_discharge_power_kw: 8`
- **THEN** after migration both keys are absent and no other battery key changed

#### Scenario: Fully migrated config
- **WHEN** the config contains neither key
- **THEN** it is not modified on startup
