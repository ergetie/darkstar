## ADDED Requirements

### Requirement: Graceful degradation settings
The `load_balancing` config section SHALL additionally support:
- `target_margin_percent`: number, default 85, valid range 50–100.
- `pause_debounce_s`: integer, default 5, valid range 0–60.
- `resume_confirm_s`: integer, default 10, valid range 5–300 — how long a balancer-paused charger's phases must fit before it re-fits (see `phase-load-balancing` "Pause below minimum current with anti-flap resume").
- `severe_overload_percent`: number, default 125, valid range 101–200.
- `ramp_up_window_s`: integer, default 60, valid range 10–600.

Each `ev_chargers[]` entry SHALL additionally support `phase_1_line` (1, 2 or 3; default 1). Out-of-range values SHALL fail validation with an error naming the key and its valid range.

`target_margin_percent` supersedes `resume_margin_percent`. On config load, a user-tuned `resume_margin_percent` with no `target_margin_percent` SHALL be migrated to `target_margin_percent` with the same value, and the old key dropped. A `resume_margin_percent` still at its old shipped default (90) carries no user intent (the template merge wrote it into every config) and SHALL be dropped so the new, more protective default applies. When both keys exist, `target_margin_percent` wins. This migration SHALL be idempotent and logged. `config.default.yaml` SHALL ship the new keys with explanatory comments.

`resume_delay_s` keeps its key and default (120 s) but no longer gates resuming a balancer-paused charger. It SHALL continue to govern restoring shed loads, the stale-sensor escalation from minimum-current fallback to pause, and the EV surplus controller's resume; its help text SHALL say so. No migration is needed: `resume_confirm_s` is added by the template merge with its default.

The load-balancing settings section SHALL expose:
- the five global fields, with plain-language help, e.g. "Aim to keep each phase at or below this share of your fuse", "Only pause if the overload lasts this long" and "A paused charger starts again once its phases have had room for the minimum current for this long";
- `phase_1_line`, shown in the EV charger's phase-switching block only when phase switching is enabled.

#### Scenario: Upgrade picks safe defaults
- **WHEN** a user with load balancing enabled upgrades without touching config
- **THEN** the balancer SHALL use an 85 % target, 5 s pause debounce, 10 s resume confirm time, 125 % severe threshold and 60 s ramp-up window

#### Scenario: Tuned legacy resume margin is migrated
- **WHEN** a config has `resume_margin_percent: 80` and no `target_margin_percent`
- **THEN** after load, `target_margin_percent` SHALL be 80 and `resume_margin_percent` SHALL be absent

#### Scenario: Untouched legacy default takes the new default
- **WHEN** a config has `resume_margin_percent: 90` (the old default) and no `target_margin_percent`
- **THEN** after load, `resume_margin_percent` SHALL be absent and the balancer SHALL use the 85 % default

#### Scenario: Invalid debounce is rejected
- **WHEN** a user saves `pause_debounce_s: 120`
- **THEN** validation SHALL fail naming `load_balancing.pause_debounce_s` and its 0–60 range

#### Scenario: Invalid resume confirm time is rejected
- **WHEN** a user saves `resume_confirm_s: 2`
- **THEN** validation SHALL fail naming `load_balancing.resume_confirm_s` and its 5–300 range

### Requirement: Phase-mode entity picker offers only writable select entities
In the EV charger settings, the phase-mode entity picker SHALL list only Home Assistant entities in the `select` or `input_select` domains. When the chosen entity exposes options, the 1-phase and 3-phase option fields SHALL offer them as a dropdown. A previously saved entity of another domain SHALL still be displayed, together with an inline error explaining that a writable select is required. Backend validation SHALL continue to reject non-select entities.

#### Scenario: Read-only sensor cannot be picked
- **WHEN** the user opens the phase-mode entity picker for a Go-e charger
- **THEN** `binary_sensor.go_echarger_417263_fsp` SHALL NOT be listed
- **AND** `select.go_echarger_417263_psm` SHALL be listed

#### Scenario: Options come from the select
- **WHEN** the user picks `select.go_echarger_417263_psm` with options `auto`, `one_phase`, `three_phases`
- **THEN** the 1-phase and 3-phase option fields SHALL offer those three values
