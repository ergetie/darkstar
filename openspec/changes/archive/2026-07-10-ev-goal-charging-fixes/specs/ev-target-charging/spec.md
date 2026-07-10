## MODIFIED Requirements

### Requirement: EV charging is driven by a target SoC and a ready-by time
EV charging SHALL be governed by a per-charger goal — a `target_soc_percent` to be reached by a `ready_by` time — not by a willingness-to-pay. The system SHALL derive the required energy from the goal and SHALL NOT require the user to set any SEK/kWh value. Goals SHALL be set via the dashboard, API, or mapped HA entities and stored in `data/ev_multi_day_state.json`; `config.yaml` SHALL NOT carry goal fields.

#### Scenario: Configured charger charges from surplus PV
- **WHEN** a charger is plugged in below its `target_soc_percent` and surplus PV is available
- **THEN** the solver SHALL charge the EV from the surplus PV rather than exporting it
- **AND** no `penalty_levels` / incentive-bucket value SHALL be required for this to happen

#### Scenario: Fresh install has no goal until one is set
- **WHEN** a charger is configured but no goal has ever been set via dashboard/API/HA
- **THEN** the charger SHALL have no charging goal (surplus-PV absorption still applies when configured)
- **AND** the dashboard SHALL prompt the user to set a goal

### Requirement: Required energy is derived from target SoC
The pipeline SHALL compute `required_kwh = max(0, (target_soc_percent − current_soc_percent)/100 · battery_capacity_kwh)`. Energy already delivered SHALL NOT be subtracted when a live SoC reading is available, because the live SoC already reflects delivered energy. Only when no live SoC reading exists (sensor unconfigured or unavailable) SHALL the pipeline fall back to subtracting the energy delivered today (from `slot_observations`) from the SoC-less estimate — and this fallback SHALL only be used when exactly one enabled charger exists, because `ev_charging_kwh` is an aggregate that cannot be attributed per charger. With multiple chargers and no SoC, the pipeline SHALL log a warning and apply no subtraction.

#### Scenario: Live SoC reflects progress — no double count
- **WHEN** the target implies 30 kWh at plug-in, 15 kWh has been delivered, and the live SoC now implies 15 kWh remaining
- **THEN** `required_kwh` SHALL be 15 (not 0)

#### Scenario: No SoC sensor, single charger
- **WHEN** a single enabled charger has no SoC reading and 10 kWh has been delivered today
- **THEN** `required_kwh` SHALL be the SoC-less estimate minus 10

#### Scenario: Target already met
- **WHEN** the current SoC already meets or exceeds `target_soc_percent`
- **THEN** `required_kwh` SHALL be 0 and no charging SHALL be scheduled (subject to keep-on behaviour)

### Requirement: Kepler enforces the target as a soft requirement
The Kepler solver SHALL add, per plugged charger with a goal, a soft constraint that delivered EV energy by the deadline meets the charger's requirement, with a shortfall penalty large enough that the target is treated as near-mandatory. The constraint SHALL be soft so that a physically unreachable target never makes the solve infeasible. When a multi-day quota schedule exists, the solver SHALL (a) cap each in-horizon day's EV energy at that day's quota, and (b) limit the soft requirement to the sum of quotas for in-horizon, pre-deadline days — so the shortfall term never forces energy planned for out-of-horizon days into the visible horizon. The shortfall penalty SHALL default to 50.0 SEK/kWh and SHALL be configurable via the advanced `kepler.ev_shortfall_penalty_sek_per_kwh` setting.

#### Scenario: Target reachable
- **WHEN** the charger can deliver the required energy before the deadline
- **THEN** the schedule SHALL deliver at least the required energy by the deadline, using the cheapest available slots
- **AND** SHALL prefer free surplus PV over grid import

#### Scenario: Target not reachable in time
- **WHEN** the window/power cannot deliver the required energy before the deadline
- **THEN** the solve SHALL remain feasible
- **AND** the charger SHALL charge as much as possible and report a shortfall ("behind")

#### Scenario: Multi-day goal with tomorrow in horizon
- **WHEN** a 5-day goal needs 60 kWh, today's quota is 12 kWh, tomorrow's quota is 12 kWh, and the plan horizon covers today and tomorrow
- **THEN** the plan SHALL deliver at most 12 kWh today and at most 12 kWh tomorrow
- **AND** the shortfall constraint SHALL require at most 24 kWh within the horizon (not 60)

#### Scenario: Shortfall penalty is configurable
- **WHEN** `kepler.ev_shortfall_penalty_sek_per_kwh` is set in config
- **THEN** the solver SHALL use that value as the shortfall penalty in the objective
- **AND** when unset, the solver SHALL default to 50.0 SEK/kWh

### Requirement: Read-only API exposes per-charger goal and progress
A `GET /api/ev/chargers` endpoint SHALL return, per charger, live HA sensor data merged with the goal and progress from the last pipeline run. The endpoint SHALL report the goal for as long as the planner would act on it (goals are durable user intent, not a cache): there SHALL be no time-based nulling of an active goal. The response SHALL include `last_planned_at` so the UI can indicate when the planner last ran, and SHALL include `n_days` for `every_n_days` goals.

#### Scenario: Charger with an active goal
- **WHEN** a plugged charger has a goal and the pipeline has run
- **THEN** the response SHALL include live `plugged_in`/`soc_percent`/`power_kw`, the goal (`target_soc_percent`, `ready_by`, `repeat`, `n_days`, resolved `deadline`), `required_kwh`/`delivered_kwh`/`remaining_kwh`, today's `daily_quota_kwh` (null when not spreading), an optional `quota_schedule`, `last_planned_at`, and `status ∈ {on_track, behind, complete, idle}`

#### Scenario: Planner has not run recently
- **WHEN** a goal exists but the pipeline has not run for hours
- **THEN** the goal SHALL still be returned (matching what the planner will act on)
- **AND** `last_planned_at` SHALL show the stale timestamp instead of the goal being nulled

#### Scenario: Pipeline state missing
- **WHEN** the state file is missing or unreadable
- **THEN** chargers SHALL be returned with `status: "idle"` and null goal-progress fields
- **AND** live HA sensor data SHALL still be populated
