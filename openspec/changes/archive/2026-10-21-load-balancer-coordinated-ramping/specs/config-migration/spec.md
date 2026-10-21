## ADDED Requirements

### Requirement: Remove balancer replan setting
Startup migration SHALL drop `load_balancing.replan_after_throttled_s` from the user's config when present, log the removal once, and leave all other keys untouched. The key SHALL also be removed from `config.default.yaml`, the settings UI and the docs. The migration SHALL be idempotent.

#### Scenario: Old config
- **WHEN** a config contains `load_balancing.replan_after_throttled_s: 600`
- **THEN** after migration the key is absent and no other key changed

#### Scenario: Fully migrated config
- **WHEN** the config no longer contains the key
- **THEN** it is not modified on startup
