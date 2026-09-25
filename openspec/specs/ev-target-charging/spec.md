# Spec: EV Target Charging

## Purpose

Defines how EV charging is governed by a per-charger goal — a target state-of-charge to be reached by a ready-by time — replacing the prior willingness-to-pay / penalty-bucket model. Charging is driven by energy need, not SEK/kWh incentive.
## Requirements
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
For each plugged charger with a goal, the Kepler solver SHALL add a soft constraint that the charger's requirement is covered by:
- EV energy delivered in-horizon by the deadline, where scheduled and planned surplus energy both count;
- plus deferred energy priced by the tiered deferral value (see `ev-deferral-value`);
- plus shortfall.

The shortfall penalty SHALL be large enough that the target is treated as near-mandatory. The constraint SHALL be soft so that a physically unreachable target never makes the solve infeasible.

The solver SHALL NOT apply per-day EV energy quota caps, and SHALL NOT reduce the requirement to a sum of quotas.

The shortfall penalty SHALL default to 50.0 SEK/kWh. It SHALL be configurable via `kepler.ev_shortfall_penalty_sek_per_kwh`, and that setting SHALL be editable in the EV settings tab as an advanced field.

#### Scenario: Target reachable
- **WHEN** the charger can deliver the required energy before the deadline and the deadline is inside the known horizon
- **THEN** the schedule SHALL deliver at least the required energy by the deadline, using the cheapest available slots
- **AND** SHALL prefer free surplus PV over grid import

#### Scenario: Target not reachable in time
- **WHEN** the window and power cannot deliver the required energy before the deadline
- **THEN** the solve SHALL remain feasible
- **AND** the charger SHALL charge as much as possible and report a shortfall ("behind")

#### Scenario: Two-day goal with all prices known
- **WHEN** a goal needs 22.2 kWh by tomorrow 23:00, all prices to the deadline are published, and tomorrow is cheaper than today
- **THEN** the plan SHALL NOT be constrained to deliver any fixed amount today
- **AND** the energy SHALL be placed in the cheapest slots across both days

#### Scenario: No incentive buckets remain
- **WHEN** the solver builds the EV objective
- **THEN** there SHALL be no `ev_bucket_charged` variable or `value_sek` reward term
- **AND** no user-set per-kWh incentive value SHALL influence EV charging (the shortfall penalty is an internal near-mandatory constraint, and the deferral value is derived from prices, not a willingness-to-pay)

#### Scenario: Shortfall penalty is configurable
- **WHEN** `kepler.ev_shortfall_penalty_sek_per_kwh` is set in config or in the EV settings tab
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

Keep-on intent SHALL be represented in the published schedule as an explicit per-slot, per-charger flag (`ev_keep_on: {charger_id: true}`), NOT as planned charging power: keep-on slots SHALL carry `0` in `ev_chargers[charger_id]` / contribute `0` to `ev_charging_kw` unless the solver genuinely planned charging energy for that slot. Published schedules SHALL therefore be energy-consistent — summing planned EV power across slots SHALL NOT include phantom keep-on energy that has no matching `grid_import_kwh`/`cost_sek`.

#### Scenario: Keep-on enabled
- **WHEN** the target is met before the ready-by time and `keep_on_after_target` is true
- **THEN** the plan SHALL keep the charger switch ON until the ready-by time
- **AND** no additional charging energy SHALL be required (the vehicle draws what it needs)

#### Scenario: Keep-on disabled (default)
- **WHEN** the target is met and `keep_on_after_target` is false
- **THEN** the plan SHALL allow the charger switch to turn OFF once the target is met

#### Scenario: Keep-on slots carry flag, not fake power
- **WHEN** the planner applies keep-on-after-target to a future slot for charger `ev1`
- **THEN** the slot's serialized `ev_keep_on` dict SHALL contain `{"ev1": true}`
- **AND** the slot's `ev_chargers["ev1"]` SHALL be `0` (absent solver-planned charging)
- **AND** the slot's `ev_charging_kw` SHALL NOT include any keep-on contribution

#### Scenario: Schedule totals are energy-consistent under keep-on
- **WHEN** a schedule contains keep-on slots
- **THEN** summing `ev_charging_kw` across the schedule SHALL yield only genuinely planned charging energy
- **AND** no slot SHALL show EV charging power without corresponding energy-balance accounting

#### Scenario: Slots without keep-on are unchanged
- **WHEN** a slot has no charger in keep-on state
- **THEN** its `ev_keep_on` field SHALL be absent or an empty dict
- **AND** solver-planned `ev_chargers`/`ev_charging_kw` values SHALL be published exactly as solved

### Requirement: Read-only API exposes per-charger goal and progress
A `GET /api/ev/chargers` endpoint SHALL return, per charger, live HA sensor data merged with the goal and progress from the last pipeline run. The endpoint SHALL report the goal for as long as the planner would act on it (goals are durable user intent, not a cache): there SHALL be no time-based nulling of an active goal. The response SHALL include `last_planned_at` so the UI can indicate when the planner last ran, and SHALL include `n_days` for `every_n_days` goals.

#### Scenario: Charger with an active goal
- **WHEN** a plugged charger has a goal and the pipeline has run
- **THEN** the response SHALL include:
  - live `plugged_in` / `soc_percent` / `power_kw`;
  - the goal: `target_soc_percent`, `ready_by`, `repeat`, `n_days`, and the resolved `deadline`;
  - `required_kwh` / `delivered_kwh` / `remaining_kwh`;
  - `planned_by_day` (a list of `{date, kwh, basis}`) and `deferral_price_source`;
  - `last_planned_at`;
  - `status ∈ {on_track, behind, complete, idle}`.
- **AND** the response SHALL NOT include `daily_quota_kwh` or `quota_schedule`

#### Scenario: Planner has not run recently
- **WHEN** a goal exists but the pipeline has not run for hours
- **THEN** the goal SHALL still be returned (matching what the planner will act on)
- **AND** `last_planned_at` SHALL show the stale timestamp instead of the goal being nulled

#### Scenario: Pipeline state missing
- **WHEN** the state file is missing or unreadable
- **THEN** chargers SHALL be returned with `status: "idle"` and null goal-progress fields
- **AND** live HA sensor data SHALL still be populated

### Requirement: Core charging does not depend on price forecasting
The goal-based charging behaviour SHALL function using only the day-ahead Nordpool prices already available to the planner. It SHALL NOT be gated behind `price_forecast.enabled`. Forecasts SHALL only be used to price deferral into post-horizon slots. When no forecast is available, deferral SHALL be priced by the conservative fallback in `ev-deferral-value`.

#### Scenario: No price-forecast module enabled
- **WHEN** `price_forecast.enabled` is false and a charger has a goal with a ready-by time inside the known horizon
- **THEN** the EV SHALL still charge toward its target using the cheapest day-ahead slots and surplus PV
- **AND** no deferral tiers SHALL be created

#### Scenario: No forecast module, deadline beyond the horizon
- **WHEN** `price_forecast.enabled` is false and the deadline is D+3
- **THEN** deferral SHALL be priced by the trailing-average or horizon-max fallback
- **AND** `deferral_price_source` SHALL reflect the fallback used

### Requirement: In-progress slot uses remaining time for EV energy
When planning starts inside a slot, the solver SHALL bound that slot's EV energy by the remaining duration (`slot_end − now`), not the full slot duration, and the planned EV kW for that slot SHALL be reported as energy divided by the remaining duration. Other energy flows in the slot SHALL be unchanged.

#### Scenario: Replan 7 minutes into a slot
- **WHEN** a replan runs at 10:22 for the 10:15–10:30 slot and the goal needs 1.2 kWh by 10:30
- **THEN** the solver SHALL allow at most `max_power_kw × 8/60` kWh in that slot
- **AND** the reported kW for that slot SHALL be the planned energy divided by 8/60 h

#### Scenario: Replan at slot start
- **WHEN** a replan runs exactly at a slot boundary
- **THEN** the EV bounds SHALL be identical to before this change

### Requirement: Post-deadline charging allowed during grace window
The solver's rule forcing zero EV energy after a charger's deadline SHALL use the effective deadline, which during a missed-goal grace window (see `ev-missed-goal-recovery`) is the extended grace deadline.

#### Scenario: Charging after missed deadline
- **WHEN** a charger is in a grace window ending 14:30
- **THEN** the solver SHALL permit EV energy in slots ending at or before 14:30
