## MODIFIED Requirements

### Requirement: Kepler enforces the target as a soft requirement
For each plugged charger with a goal, the Kepler solver SHALL add a soft constraint that the charger's requirement is covered by:
- EV energy delivered to the car in-horizon by the deadline. Scheduled and planned surplus energy both count, after charging losses as defined by `ev-charging-losses` (efficiency, overhead while on, start loss);
- plus deferred energy priced by the tiered deferral value (see `ev-deferral-value`);
- plus shortfall.

The shortfall penalty SHALL be large enough that the target is treated as near-mandatory. The constraint SHALL be soft so that a physically unreachable target never makes the solve infeasible.

The solver SHALL NOT apply per-day EV energy quota caps, and SHALL NOT reduce the requirement to a sum of quotas.

The shortfall penalty SHALL default to 50.0 SEK/kWh. It SHALL be configurable via `kepler.ev_shortfall_penalty_sek_per_kwh`, and that setting SHALL be editable in the EV settings tab as an advanced field.

#### Scenario: Target reachable
- **WHEN** the charger can deliver the required energy before the deadline and the deadline is inside the known horizon
- **THEN** the schedule SHALL deliver at least the required energy to the car, after losses, by the deadline, using the cheapest available slots
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
