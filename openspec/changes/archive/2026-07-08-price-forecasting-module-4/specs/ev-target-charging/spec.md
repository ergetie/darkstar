## ADDED Requirements

### Requirement: EV charging is driven by a target SoC and a ready-by time
EV charging SHALL be governed by a per-charger goal — a `target_soc_percent` to be reached by a `ready_by` time — not by a willingness-to-pay. The system SHALL derive the required energy from the goal and SHALL NOT require the user to set any SEK/kWh value.

#### Scenario: Configured charger charges from surplus PV
- **WHEN** a charger is plugged in below its `target_soc_percent` and surplus PV is available
- **THEN** the solver SHALL charge the EV from the surplus PV rather than exporting it
- **AND** no `penalty_levels` / incentive-bucket value SHALL be required for this to happen

#### Scenario: Default goal charges out of the box
- **WHEN** a charger is configured with the shipped defaults (`target_soc_percent: 80`, `ready_by: "07:00"`, `repeat: daily`) and nothing else
- **THEN** the EV SHALL charge toward 80% by 07:00 without any further configuration
- **AND** the prior empty-`penalty_levels` "never charges" behaviour SHALL NOT occur

### Requirement: Required energy is derived from target SoC
The pipeline SHALL compute `required_kwh = max(0, (target_soc_percent − current_soc_percent)/100 · battery_capacity_kwh)` minus the EV energy already delivered in the current charging cycle (from `slot_observations`). The user expresses the goal as a percentage; the system works in kWh internally.

#### Scenario: Partial charge already delivered
- **WHEN** `target_soc_percent` implies 40 kWh and 25 kWh has been delivered since plug-in
- **THEN** `required_kwh` SHALL be 15

#### Scenario: Target already met
- **WHEN** the current SoC already meets or exceeds `target_soc_percent`
- **THEN** `required_kwh` SHALL be 0 and no charging SHALL be scheduled (subject to keep-on behaviour)

### Requirement: Kepler enforces the target as a soft requirement
The Kepler solver SHALL add, per plugged charger with a goal, a soft constraint that delivered EV energy by the deadline meets `required_kwh`, with a shortfall penalty large enough that the target is treated as near-mandatory. The constraint SHALL be soft so that a physically unreachable target never makes the solve infeasible. The incentive-bucket variables and their reward term SHALL be removed. The shortfall penalty SHALL default to 50.0 SEK/kWh and SHALL be configurable via the advanced `kepler.ev_shortfall_penalty_sek_per_kwh` setting.

#### Scenario: Target reachable
- **WHEN** the charger can deliver `required_kwh` before the deadline
- **THEN** the schedule SHALL deliver at least `required_kwh` by the deadline, using the cheapest available slots
- **AND** SHALL prefer free surplus PV over grid import

#### Scenario: Target not reachable in time
- **WHEN** the window/power cannot deliver `required_kwh` before the deadline
- **THEN** the solve SHALL remain feasible
- **AND** the charger SHALL charge as much as possible and report a shortfall ("behind")

#### Scenario: No incentive buckets remain
- **WHEN** the solver builds the EV objective
- **THEN** there SHALL be no `ev_bucket_charged` variable or `value_sek` reward term
- **AND** no user-set per-kWh incentive value SHALL influence EV charging (the shortfall penalty is an internal near-mandatory constraint, not a willingness-to-pay)

#### Scenario: Shortfall penalty is configurable
- **WHEN** `kepler.ev_shortfall_penalty_sek_per_kwh` is set in config
- **THEN** the solver SHALL use that value as the shortfall penalty in the objective
- **AND** when unset, the solver SHALL default to 50.0 SEK/kWh

### Requirement: Excess-PV surplus routing is owned by excess_pv.priority[] (no charge_priority here)
Surplus-PV self-consumption ordering SHALL be governed by the already-shipped `excess_pv.priority[]` list (the `excess-pv-priority-dispatch` capability) — the home battery is implicitly first via `soc_threshold_percent`, and `ev` entries in the priority list route surplus to EV chargers ordered by rank-scaled reward. **This change SHALL NOT introduce a per-charger `charge_priority` field, an in-solver self-consumption tie-break term, or any parallel surplus-routing code path.** A user who wants EV-first surplus moves the `ev` entry up the existing priority-list editor (under Settings → Advanced → "Excess PV Dispatch").

#### Scenario: Surplus absorption requires the charger be listed in excess_pv.priority[]
- **WHEN** a current-type charger has a goal but is NOT listed as an `ev` entry in `excess_pv.priority[]`
- **THEN** the solver SHALL create no `ev_surplus_kw` variable for it and the charger SHALL only receive deadline-target scheduled charging (cheapest day-ahead slot prices)
- **AND** export SHALL still occur when PV exceeds household + battery demand

#### Scenario: Binary charger is never a surplus sink
- **WHEN** an `ev` priority-list entry references a `type: binary` charger
- **THEN** the solver SHALL silently drop it (no `ev_surplus_kw` variable created), as defense in depth alongside config-API rejection
- **AND** the binary charger SHALL still receive the deadline-target scheduled charging (`ev_charge[d][t] = 1` for whole slots)

#### Scenario: Battery-absent system still routes surplus
- **WHEN** the system has no house battery (`capacity_kwh == 0`) and a current-type charger is listed in `excess_pv.priority[]`
- **THEN** the `soc_above_threshold` big-M gate SHALL collapse (threshold 0, M 0) and surplus SHALL route to the configured sinks immediately without waiting for a battery to fill

### Requirement: Keep charger on after target
A per-charger `keep_on_after_target` (default false) SHALL, when true, keep the charger's intended switch state ON through the ready-by time after the target is met, so the vehicle can pre-condition / run its heater.

#### Scenario: Keep-on enabled
- **WHEN** the target is met before the ready-by time and `keep_on_after_target` is true
- **THEN** the plan SHALL keep the charger switch ON until the ready-by time
- **AND** no additional charging energy SHALL be required (the vehicle draws what it needs)

#### Scenario: Keep-on disabled (default)
- **WHEN** the target is met and `keep_on_after_target` is false
- **THEN** the plan SHALL allow the charger switch to turn OFF once the target is met

### Requirement: Read-only API exposes per-charger goal and progress
A `GET /api/ev/chargers` endpoint SHALL return, per charger, live HA sensor data merged with the goal and progress from the last pipeline run.

#### Scenario: Charger with an active goal
- **WHEN** a plugged charger has a goal and the pipeline has run
- **THEN** the response SHALL include live `plugged_in`/`soc_percent`/`power_kw`, the goal (`target_soc_percent`, `ready_by`, `repeat`, resolved `deadline`), `required_kwh`/`delivered_kwh`/`remaining_kwh`, today's `daily_quota_kwh` (null when not spreading), an optional `quota_schedule`, and `status ∈ {on_track, behind, complete, idle}`

#### Scenario: Pipeline state missing
- **WHEN** the state file is missing or stale
- **THEN** chargers SHALL be returned with `status: "idle"` and null goal-progress fields
- **AND** live HA sensor data SHALL still be populated

### Requirement: Core charging does not depend on price forecasting
The goal-based charging behaviour SHALL function using only the day-ahead Nordpool prices already available to the planner. It SHALL NOT be gated behind `price_forecast.enabled`. Only multi-day spreading across days beyond the day-ahead horizon SHALL use the 7-day forecast.

#### Scenario: No price-forecast module enabled
- **WHEN** `price_forecast.enabled` is false and a charger has a goal with a near ready-by time
- **THEN** the EV SHALL still charge toward its target using the cheapest day-ahead slots and surplus PV
- **AND** no daily quota SHALL be applied
