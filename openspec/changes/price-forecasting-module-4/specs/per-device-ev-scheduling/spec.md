## MODIFIED Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), and the goal fields below. The goal fields replace the prior `departure_time` + `penalty_levels` model.

Goal fields:
- `target_soc_percent` (int, 0–100, default 80) — the SoC the vehicle should reach.
- `ready_by` (string, `HH:MM` 24h) — the time the target should be met by.
- `repeat` (enum `daily` | `weekdays` | `weekends` | `every_n_days` | `none`, default `daily`) — how the ready-by time recurs. `none` = a one-off.
- `n_days` (int) — used when `repeat: every_n_days`.
- `ready_by_date` (string, ISO date) — used when `repeat: none` (the specific date for the one-off).
- `keep_on_after_target` (boolean, default false) — keep the switch ON through the ready-by time after the target is met.
- `charge_priority` (enum `battery` | `ev`, default `battery`) — who gets free surplus PV first.

`penalty_levels` is **retired**: if present it SHALL be ignored for scheduling, SHALL emit a one-release deprecation warning, and SHALL be auto-migrated to `target_soc_percent` equal to the highest configured `max_soc`. `departure_time` SHALL be accepted as a deprecated alias for `ready_by` (with a warning). The config loader SHALL use a YAML 1.2 parser (ruamel.yaml) so unquoted `HH:MM` values read as strings, and SHALL accept the time as either `"HH:MM"` or an integer minutes-since-midnight (0–1439), converting integers to `"HH:MM"`; out-of-range values SHALL be treated as invalid.

#### Scenario: Charger with a daily goal
- **WHEN** a charger has `target_soc_percent: 80`, `ready_by: "07:00"`, `repeat: daily`
- **THEN** the pipeline SHALL aim to reach 80% by the next 07:00 and repeat every day

#### Scenario: Charger with a one-off date
- **WHEN** a charger has `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, `target_soc_percent: 100`
- **THEN** the pipeline SHALL aim to reach 100% by 2026-06-12 07:00 and SHALL become inert after that datetime passes

#### Scenario: Legacy penalty_levels present
- **WHEN** a charger config still contains `penalty_levels`
- **THEN** the loader SHALL ignore them for scheduling, emit a deprecation warning, and set `target_soc_percent` to the highest configured `max_soc`

#### Scenario: Legacy departure_time alias
- **WHEN** a charger config uses `departure_time: "07:00"` and no `ready_by`
- **THEN** the loader SHALL treat `07:00` as `ready_by` and emit a deprecation warning

#### Scenario: Charger with no switch entity
- **WHEN** an enabled charger has `switch_entity: ""` or the field is absent
- **THEN** the executor SHALL skip switch control for that charger (planning-only mode)

#### Scenario: Unquoted HH:MM in config.yaml read correctly
- **WHEN** config.yaml contains `ready_by: 16:00` (unquoted)
- **THEN** the YAML 1.2 parser SHALL read it as the string `"16:00"` (not the integer `960`)

### Requirement: Per-device ready-by resolution
The pipeline SHALL resolve each charger's next ready-by datetime independently from its `ready_by` + `repeat` (or `ready_by_date` when `repeat: none`). This resolved datetime SHALL be used as the Kepler deadline for that charger. A charger past a non-repeating ready-by datetime SHALL have no deadline (inert).

#### Scenario: Daily repeat resolves to the next occurrence
- **WHEN** `ready_by: "07:00"`, `repeat: daily`, and the current time is 22:00
- **THEN** the resolved deadline SHALL be tomorrow 07:00

#### Scenario: Every-N-days repeat
- **WHEN** `repeat: every_n_days`, `n_days: 2`, and today is not a charging day
- **THEN** the resolved deadline SHALL be the `ready_by` time on the next matching day

#### Scenario: One-off date in the future
- **WHEN** `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, and today is 2026-06-08
- **THEN** the resolved deadline SHALL be 2026-06-12 07:00

#### Scenario: One-off date already passed
- **WHEN** `repeat: none` and the `ready_by_date`/`ready_by` datetime is in the past
- **THEN** the charger SHALL have no deadline and SHALL NOT be scheduled
