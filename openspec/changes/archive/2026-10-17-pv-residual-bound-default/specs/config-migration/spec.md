## ADDED Requirements

### Requirement: Migrate the old PV residual bound default
Migration SHALL replace a user `forecasting.pv_residual_bound_fraction` equal to exactly 0.25 (the former shipped default, which carries no user intent) with 1.0. Any other user value, including 0, SHALL be kept. A missing key SHALL take the template default via the normal merge. The migration SHALL be idempotent and SHALL report a change only when it rewrites the value.

#### Scenario: Old default replaced
- **WHEN** the user config has `pv_residual_bound_fraction: 0.25`
- **THEN** it SHALL become 1.0 and the config SHALL be written

#### Scenario: User-tuned value kept
- **WHEN** the value is 0.4, 0 or 2.0
- **THEN** it SHALL be unchanged

#### Scenario: Key missing
- **WHEN** the key is absent
- **THEN** the migration SHALL make no change and the template merge SHALL supply 1.0

#### Scenario: Idempotent
- **WHEN** migration runs twice on a config with 0.25
- **THEN** the second run SHALL make no change and SHALL NOT rewrite the file

#### Scenario: Reflex does not interfere
- **WHEN** Reflex runs its parameter tuning
- **THEN** `forecasting.pv_residual_bound_fraction` SHALL NOT be modified by it
