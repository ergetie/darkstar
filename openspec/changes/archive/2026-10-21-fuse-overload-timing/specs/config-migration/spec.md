## ADDED Requirements

### Requirement: Remove balancer pause-delay and severe-overload settings
Startup migration SHALL drop `load_balancing.pause_debounce_s` and `load_balancing.severe_overload_percent` from the user's config when present, log each removal, and leave all other keys untouched. Both keys SHALL be added to the deprecated-key list used by `remove_deprecated_keys` and removed from `config.default.yaml`, the config loader, the API validator, the settings UI and the docs. The migration SHALL be idempotent and SHALL NOT make `replan_after_throttled_s` supported again.

#### Scenario: Old config
- **WHEN** a config contains `load_balancing.pause_debounce_s: 5` and `load_balancing.severe_overload_percent: 125`
- **THEN** it SHALL load without validation errors or user-facing warnings
- **AND** after the startup sweep both keys are absent, each removal is logged, the result is written through the existing atomic write with backup, and no other key changed

#### Scenario: Fully migrated config
- **WHEN** the config contains neither key
- **THEN** it is not modified on startup

#### Scenario: Template merge does not bring the keys back
- **WHEN** the template merge runs on a config without the keys
- **THEN** the keys SHALL NOT be re-added, because `config.default.yaml` no longer contains them
