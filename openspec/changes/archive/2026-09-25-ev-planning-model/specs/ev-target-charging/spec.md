## MODIFIED Requirements

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
