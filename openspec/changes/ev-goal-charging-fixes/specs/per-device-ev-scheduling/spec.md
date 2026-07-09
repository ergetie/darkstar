## MODIFIED Requirements

### Requirement: Per-device EV config structure
Each entry in `ev_chargers[]` SHALL support the following per-device fields: `switch_entity` (string, HA entity ID), `replan_on_plugin` (boolean, default true), `replan_on_unplug` (boolean, default false), plus hardware facts (`sensor`, `soc_sensor`, `plug_sensor`, `battery_capacity_kwh`, `max_power_kw`, `type`, current/phase entities) and the optional HA goal entities (`ha_ready_by_entity`, `ha_target_soc_entity`).

**Goal fields do NOT live in config.** `target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, and `keep_on_after_target` SHALL NOT be read from `config.yaml`; goals are owned by `data/ev_multi_day_state.json` via the dashboard/API/HA sync (see `ev-schedule-api`). If any goal field (or the legacy `departure_time` / `penalty_levels`) is present in config, the loader SHALL log a deprecation warning naming the dashboard as the place to set goals, and SHALL ignore the value for scheduling. Malformed values in these ignored fields SHALL NOT crash config loading.

**No `charge_priority` field.** Surplus-PV routing is owned by the existing `excess_pv.priority[]` list (see `excess-pv-priority-dispatch`).

#### Scenario: Config with goal fields is tolerated but ignored
- **WHEN** a charger config still contains `target_soc_percent: 90` or `departure_time: "07:00"`
- **THEN** the loader SHALL emit a deprecation warning pointing to the dashboard
- **AND** the value SHALL NOT influence scheduling (the state-file goal, or absence of one, governs)

#### Scenario: Malformed legacy goal value does not crash
- **WHEN** a charger config contains `target_soc_percent: "80%"`
- **THEN** config loading SHALL succeed with a warning (no ValueError propagation)

#### Scenario: Charger with no switch entity
- **WHEN** an enabled charger has `switch_entity: ""` or the field is absent
- **THEN** the executor SHALL skip switch control for that charger (planning-only mode)

### Requirement: Per-device ready-by resolution
The pipeline SHALL resolve each charger's next ready-by datetime independently from its state-file goal (`ready_by` + `repeat`, `n_days` when `repeat: every_n_days`, or `ready_by_date` when `repeat: none`). Resolution SHALL use **one shared resolver function** used identically by the planner pipeline, the schedule API, and the HA sync — divergent duplicate implementations are a defect. The shared resolver SHALL default `n_days` to 1 and SHALL anchor the `every_n_days` cycle to the goal's `last_updated` date (deterministic and user-controllable by re-saving), not a hard-coded epoch. A missing/null `repeat` SHALL be treated as `daily` (never string-matched against `"none"`). This resolved datetime SHALL be used as the Kepler deadline for that charger. A charger past a non-repeating ready-by datetime SHALL have no deadline (inert).

#### Scenario: Daily repeat resolves to the next occurrence
- **WHEN** `ready_by: "07:00"`, `repeat: daily`, and the current time is 22:00
- **THEN** the resolved deadline SHALL be tomorrow 07:00

#### Scenario: Every-N-days repeat
- **WHEN** `repeat: every_n_days`, `n_days: 3`, and the goal was last saved today
- **THEN** the resolved deadline SHALL be the `ready_by` time 3 days from the save date, and every 3 days thereafter
- **AND** the API, planner, and HA sync SHALL all resolve the same datetime

#### Scenario: One-off date in the future
- **WHEN** `repeat: none`, `ready_by_date: "2026-06-12"`, `ready_by: "07:00"`, and today is 2026-06-08
- **THEN** the resolved deadline SHALL be 2026-06-12 07:00

#### Scenario: One-off date already passed
- **WHEN** `repeat: none` and the `ready_by_date`/`ready_by` datetime is in the past
- **THEN** the charger SHALL have no deadline and SHALL NOT be scheduled

#### Scenario: Null repeat from a legacy state file
- **WHEN** a state-file goal has `repeat: null`
- **THEN** the resolver SHALL treat it as `daily` (not as the one-off `"none"` mode)

## REMOVED Requirements

### Requirement: Per-device SoC and incentive bucket constraints
**Reason**: Stale leftover — the incentive-bucket model (`penalty_levels`) was retired by `price-forecasting-module-4` in favor of goal-based target charging; this requirement was never updated at archive time and no longer describes the system.
**Migration**: Per-device prioritization under scarcity now emerges from the goal-based soft shortfall constraints (see `ev-target-charging`); no config migration needed beyond the already-specified `penalty_levels` deprecation.
