# Delta: config-migration

## ADDED Requirements

### Requirement: Strip deprecated EV goal fields from chargers
The migration SHALL remove all deprecated EV goal fields from every `ev_chargers[]` entry: `departure_time`, `penalty_levels`, `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, and `keep_on_after_target`. Each removal SHALL be logged. The set of deprecated goal field names SHALL be defined in exactly one module and shared with the executor's deprecation warning (no duplicated hand-maintained lists). Old values are NOT preserved anywhere in the config; the migration's standard automatic backup is the only recovery path.

#### Scenario: Legacy departure_time stripped
- **WHEN** a charger entry contains `departure_time: 1200` (or any value, valid or malformed)
- **THEN** after migration the entry SHALL NOT contain a `departure_time` key
- **AND** a config file write SHALL occur (with the standard automatic backup)

#### Scenario: Legacy penalty_levels stripped
- **WHEN** a charger entry contains a `penalty_levels` list
- **THEN** after migration the entry SHALL NOT contain a `penalty_levels` key

#### Scenario: Clean config untouched
- **WHEN** no charger entry contains any deprecated goal field
- **THEN** this migration step SHALL report no change (idempotent, no write triggered by this step)

## REMOVED Requirements

### Requirement: Migrate global EV departure time into first charger
**Reason**: `departure_time` is a deprecated goal field with no runtime effect since the goal-based EV charging model (`ev-goal-charging-fixes`); copying root `ev_departure_time` into `ev_chargers[0]` plants a field that the new strip step immediately removes. Root `ev_departure_time` remains in `DEPRECATED_KEYS` and is swept as before.
**Migration**: Set charging goals (target SoC, ready-by) on the dashboard EV card; they are stored in `data/ev_multi_day_state.json`.

## MODIFIED Requirements

### Requirement: Config default template updated
The `config.default.yaml` template SHALL include the per-device fields `switch_entity`, `replan_on_plugin`, and `replan_on_unplug` in `ev_chargers[]` entries with appropriate defaults. The template SHALL NOT include any deprecated EV goal field (`departure_time`, `penalty_levels`, etc.). The global `ev_departure_time` and `executor.ev_charger` section SHALL be removed from the template.

#### Scenario: New installation gets per-device defaults
- **WHEN** a new user starts with `config.default.yaml`
- **THEN** each `ev_chargers[]` entry SHALL include `switch_entity: ""`, `replan_on_plugin: true`, `replan_on_unplug: false`
- **AND** no `ev_chargers[]` entry SHALL include `departure_time` or `penalty_levels`
- **AND** no global `ev_departure_time` or `executor.ev_charger` section SHALL exist
