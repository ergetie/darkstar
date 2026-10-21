## MODIFIED Requirements

### Requirement: Graceful degradation settings
The `load_balancing` config section SHALL additionally support the graceful-degradation keys, validation, migration and settings exposure specified in the scenarios below.

#### Scenario: Graceful degradation config keys
- **WHEN** the `load_balancing` config section is read
- **THEN** it SHALL support `target_margin_percent`: number, default 85, valid range 50–100
- **AND** `resume_confirm_s`: integer, default 10, valid range 5–300, which is how long a balancer-paused charger's phases must fit before it re-fits (see `phase-load-balancing` "Pause below minimum current with anti-flap resume")
- **AND** `ramp_up_window_s`: integer, default 60, valid range 10–600, used only as the averaging window for increases and restores (not as a hold-off)
- **AND** `fuse_preset`, `fuse_safety_percent` and `fuse_custom_points` as specified in `fuse-overload-timing` "Fuse configuration keys"
- **AND** `pause_debounce_s` and `severe_overload_percent` are no longer supported

#### Scenario: phase_1_line and range validation
- **WHEN** an `ev_chargers[]` entry or one of the new keys is validated
- **THEN** each `ev_chargers[]` entry SHALL additionally support `phase_1_line` (1, 2 or 3; default 1)
- **AND** out-of-range values SHALL fail validation with an error naming the key and its valid range

#### Scenario: target_margin_percent supersedes resume_margin_percent
- **WHEN** the config is loaded
- **THEN** `target_margin_percent` supersedes `resume_margin_percent`
- **AND** a user-tuned `resume_margin_percent` with no `target_margin_percent` SHALL be migrated to `target_margin_percent` with the same value, and the old key dropped
- **AND** a `resume_margin_percent` still at its old shipped default (90) carries no user intent (the template merge wrote it into every config) and SHALL be dropped so the new, more protective default applies
- **AND** when both keys exist, `target_margin_percent` wins
- **AND** this migration SHALL be idempotent and logged
- **AND** `config.default.yaml` SHALL ship the new keys with explanatory comments

#### Scenario: resume_delay_s scope
- **WHEN** a balancer-paused charger is resumed
- **THEN** `resume_delay_s` keeps its key and default (120 s) but no longer gates resuming a balancer-paused charger
- **AND** it SHALL continue to govern restoring shed loads, the stale-sensor escalation from minimum-current fallback to pause, and the EV surplus controller's resume; its help text SHALL say so
- **AND** no migration is needed: `resume_confirm_s` is added by the template merge with its default

#### Scenario: Settings section exposes global fields
- **WHEN** the load-balancing settings section is displayed
- **THEN** it SHALL expose the global fields, with plain-language help, e.g. "Aim to keep each phase at or below this share of your fuse" and "A paused charger starts again once its phases have had room for the minimum current for this long"
- **AND** it SHALL expose `phase_1_line`, shown in the EV charger's phase-switching block only when phase switching is enabled

#### Scenario: Upgrade picks safe defaults
- **WHEN** a user with load balancing enabled upgrades without touching config
- **THEN** the balancer SHALL use an 85 % target, 10 s resume confirm time, the Typ C fuse curve with 80 % safety and a 60 s ramp-up averaging window

#### Scenario: Tuned legacy resume margin is migrated
- **WHEN** a config has `resume_margin_percent: 80` and no `target_margin_percent`
- **THEN** after load, `target_margin_percent` SHALL be 80 and `resume_margin_percent` SHALL be absent

#### Scenario: Untouched legacy default takes the new default
- **WHEN** a config has `resume_margin_percent: 90` (the old default) and no `target_margin_percent`
- **THEN** after load, `resume_margin_percent` SHALL be absent and the balancer SHALL use the 85 % default

#### Scenario: Invalid debounce is rejected
- **WHEN** a config contains `pause_debounce_s: 120` or `severe_overload_percent: 300`
- **THEN** it SHALL load without a validation error and the keys SHALL be removed by the deprecated-key sweep (see `config-migration` "Remove balancer pause-delay and severe-overload settings")


#### Scenario: Invalid resume confirm time is rejected
- **WHEN** a user saves `resume_confirm_s: 2`
- **THEN** validation SHALL fail naming `load_balancing.resume_confirm_s` and its 5–300 range
