# ev-deferral-value Specification

## Purpose
Define how the planner values deferring EV charging past the plan horizon, using per-slot known or forecast prices and a deadline-aware risk margin.
## Requirements
### Requirement: Goal window is classified into known and forecast time per slot
For each plugged charger with an active goal, the pipeline SHALL classify every slot from now until the goal deadline as either **in-horizon** or **post-horizon**.

#### Scenario: Deadline inside the known horizon
- **WHEN** the deadline is 2026-09-26 23:00 and published prices cover through 2026-09-26 23:45
- **THEN** there SHALL be zero post-horizon slots for that goal

#### Scenario: Deadline beyond the known horizon
- **WHEN** it is 10:00, published prices cover today only, and the deadline is tomorrow 07:00
- **THEN** tomorrow's slots from 00:00 to 07:00 SHALL be post-horizon slots priced from the forecast

#### Scenario: Forecast spot is converted to import price
- **WHEN** a post-horizon slot has forecast spot 0.30 SEK/kWh
- **THEN** its deferral price SHALL be the import price computed from 0.30 SEK/kWh with the configured grid fee, energy tax and VAT, not 0.30

#### Scenario: In-horizon and post-horizon slot classification
- **WHEN** the pipeline classifies a slot between now and the goal deadline
- **THEN** a slot that is part of the Kepler plan, which means it has a published Nordpool price, SHALL be **in-horizon**
- **AND** a slot that ends after the last planned slot and at or before the deadline SHALL be **post-horizon**

#### Scenario: Post-horizon slot pricing
- **WHEN** a post-horizon slot is priced
- **THEN** it SHALL be priced with the published spot price from the known-price resolver when one exists
- **AND** otherwise with the latest-issue forecast `spot_p50`
- **AND** spot values SHALL be converted to import prices with the same tariff function used for in-horizon prices (grid transfer fee, energy tax, VAT)

### Requirement: Undelivered in-horizon energy is priced by tiered deferral value
Kepler SHALL model the goal requirement as `delivered_in_horizon + Σ deferred_k + shortfall ≥ required_kwh`, with the tier, shortfall and pricing variables defined in the scenarios below.

#### Scenario: All prices known, next day cheaper
- **WHEN** 22.2 kWh is required by tomorrow 23:00, all prices up to the deadline are published, today's remaining slots cost about 2.4 SEK/kWh, and tomorrow's night slots cost about 1.0 SEK/kWh
- **THEN** the plan SHALL schedule the goal energy in tomorrow's cheap slots
- **AND** SHALL NOT be forced to schedule any grid charging today

#### Scenario: Forecast cheaper than every known slot
- **WHEN** the deadline is D+3, 10 kWh is required, and the risk-adjusted deferral price of the cheapest post-horizon tier is below every in-horizon import price
- **THEN** the plan SHALL schedule no grid charging in the horizon for that goal
- **AND** planned surplus-PV charging MAY still occur because it is cheaper than deferral

#### Scenario: Known slot cheaper than forecast
- **WHEN** an in-horizon slot's import price is below the cheapest risk-adjusted deferral tier
- **THEN** the plan SHALL charge in that slot

#### Scenario: Large requirement uses dearer tiers
- **WHEN** the requirement exceeds the capacity of the cheapest deferral tier
- **THEN** the marginal deferred kWh SHALL be priced at the next tier's price
- **AND** in-horizon slots cheaper than that marginal tier SHALL be used

#### Scenario: Forecast turns out wrong after publication
- **WHEN** a re-plan runs after D+1 prices are published and they are higher than the forecast used earlier
- **THEN** those slots SHALL be in-horizon at their published prices
- **AND** the deferral decision SHALL be recomputed from the remaining post-horizon forecast

#### Scenario: Deferral tier variables
- **WHEN** Kepler builds the deferral tiers
- **THEN** each `deferred_k` SHALL be a continuous tier variable, bounded by `0 ≤ deferred_k ≤ cap_k`
- **AND** tiers SHALL be built by sorting the post-horizon slots ascending by deferral price and grouping them into at most 24 consecutive-rank blocks
- **AND** `cap_k` SHALL be the sum over the block's slots of `charger_max_kw × slot_hours`

#### Scenario: Tier price and shortfall
- **WHEN** Kepler prices the tiers and the shortfall
- **THEN** each tier SHALL be priced at the block's energy-weighted deferral price × `(1 + effective_margin)`, where `effective_margin` is the deadline-ramped risk margin defined in "Deferral risk margin is user-configurable and ramps toward the deadline"
- **AND** the shortfall SHALL keep the existing shortfall penalty

#### Scenario: No post-horizon slots and no quota caps
- **WHEN** there are no post-horizon slots
- **THEN** no tier variables SHALL exist and the requirement SHALL reduce to `delivered_in_horizon + shortfall ≥ required_kwh`
- **AND** there SHALL be no per-day energy quota caps on EV charging in the solver

### Requirement: Post-horizon capacity bounds deferral
The total deferrable energy SHALL NOT exceed the physical post-horizon capacity, which is the sum of `charger_max_kw × slot_hours` over the post-horizon slots before the deadline. Any requirement beyond that capacity SHALL have to be met in-horizon or be reported as shortfall.

#### Scenario: Tail too short to finish the goal
- **WHEN** 30 kWh is required, the charger delivers 6.9 kW, and the post-horizon window before the deadline is 2 h (13.8 kWh capacity)
- **THEN** at least 16.2 kWh SHALL be scheduled in-horizon, or appear as shortfall if the horizon cannot deliver it

### Requirement: Deferral pricing degrades conservatively when forecasts are missing
When a post-horizon slot has neither a published nor a forecast price, its deferral price SHALL be the trailing 14-day average realised import price when available, otherwise the maximum in-horizon import price, as specified in the scenarios below.

#### Scenario: Forecast fetch fails for a D+4 goal
- **WHEN** the forecast query raises an error and 14 days of observations exist
- **THEN** post-horizon slots SHALL be priced at the trailing average import price × (1 + effective_margin)
- **AND** `deferral_price_source` SHALL be `trailing_average`
- **AND** the plan SHALL NOT front-load the entire requirement into the horizon solely because of the failure

#### Scenario: Cold start with no history
- **WHEN** no forecast and fewer than 2 days of observations exist
- **THEN** post-horizon slots SHALL be priced at the maximum in-horizon import price
- **AND** `deferral_price_source` SHALL be `horizon_max`

#### Scenario: Deferral price fallback order
- **WHEN** a post-horizon slot has neither a published nor a forecast price
- **THEN** its deferral price SHALL be the trailing 14-day average realised import price from `slot_observations`, times `(1 + effective_margin)`
- **AND** if that is unavailable, its deferral price SHALL be the maximum in-horizon import price

#### Scenario: Fallback warning and price source persisted
- **WHEN** the fallback deferral price is used
- **THEN** the pipeline SHALL log a warning
- **AND** it SHALL persist per charger a `deferral_price_source` of `forecast`, `trailing_average`, or `horizon_max` (the least-reliable source used)
- **AND** a missing forecast SHALL NOT disable the deadline-aware model

### Requirement: Deferral risk margin is user-configurable and ramps toward the deadline
The deferral risk margin SHALL be a user-set base that grows linearly as the goal's deadline approaches, using the settings, formula and UI behavior specified in the scenarios below.

#### Scenario: Default margin far from the deadline
- **WHEN** the settings are absent from config and the deadline is 72 h away
- **THEN** the effective margin SHALL be 12%

#### Scenario: Margin ramps as the deadline approaches
- **GIVEN** default settings
- **WHEN** the deadline is 24 h away
- **THEN** the effective margin SHALL be 31%
- **AND** when a later re-plan runs with the deadline 6 h away, the effective margin SHALL be 45.25%

#### Scenario: Ramp disabled
- **GIVEN** `deferral_risk_margin_max_percent` equals `deferral_risk_margin_percent`
- **WHEN** the deadline is 2 h away
- **THEN** the effective margin SHALL equal the base

#### Scenario: Out-of-range value rejected
- **WHEN** the user saves a base of 150, or a maximum below the base
- **THEN** config validation SHALL reject the value with an actionable error naming the key

#### Scenario: Goal Planning explains itself
- **WHEN** the user opens the EV settings tab
- **THEN** the "Goal Planning" section SHALL show an info box under its title covering charge-now-versus-wait, the risk margin and ramp, and the shortfall penalty
- **AND** the box SHALL initially show only a one-line summary, with the full text revealed by an expand control

#### Scenario: Risk margin settings and defaults
- **WHEN** the deferral risk margin settings are configured
- **THEN** `ev_planning.deferral_risk_margin_percent` (base) SHALL default to 12 and SHALL accept values from 0 to 100
- **AND** `ev_planning.deferral_risk_margin_max_percent` SHALL default to 50 and SHALL accept values from the base up to 200
- **AND** `ev_planning.deferral_risk_ramp_hours` SHALL default to 48 and SHALL accept values from 1 to 168

#### Scenario: Effective margin computed each planner run
- **WHEN** the planner runs for a charger with a goal, with `h` = hours from now to the deadline
- **THEN** the planner SHALL compute `effective_margin = base + (max − base) × clamp(1 − h / ramp_hours, 0, 1)`
- **AND** the planner SHALL persist `effective_margin_percent` per charger alongside `deferral_price_source`

#### Scenario: Risk margin settings editable with help text
- **WHEN** the EV settings tab is displayed
- **THEN** all three settings SHALL be editable, with help text explaining that a higher margin charges earlier and relies less on price forecasts, and that the margin rises from the base to the maximum over the ramp window before the deadline

#### Scenario: Goal Planning info box
- **WHEN** the EV settings tab's "Goal Planning" section is displayed
- **THEN** it SHALL show an info box directly under its title that explains in plain language how Darkstar decides between charging now and waiting for cheaper forecast prices (published prices are optimised directly; later hours are priced at the published or forecast price plus the risk margin), what the risk margin and its ramp do, and what the shortfall penalty means
- **AND** the info box SHALL start collapsed, showing only its title and a one-line summary; an accessible expand/collapse control SHALL reveal the full explanation

### Requirement: Planner publishes a planned per-day estimate
After each solve, the pipeline SHALL persist, and `GET /api/ev/chargers` SHALL return, a `planned_by_day` list per charger with a goal. It SHALL contain one entry `{date, kwh, basis}` per local calendar day from today through the deadline day, with kWh and basis determined as specified in the scenarios below.

#### Scenario: Two-day goal with both days published
- **WHEN** the goal spans today and tomorrow and all prices are published
- **THEN** `planned_by_day` SHALL have two entries, both with `basis: "known"`

#### Scenario: D+3 goal before tomorrow's auction
- **WHEN** only today's prices are published
- **THEN** today SHALL be `known` and D+1..D+3 SHALL be `estimated`

#### Scenario: Old state file keys are ignored
- **WHEN** the state file still contains `quota_schedule` from a previous version
- **THEN** the API SHALL NOT return it and SHALL NOT fail

#### Scenario: Planned per-day kWh by horizon
- **WHEN** the pipeline builds a `planned_by_day` entry
- **THEN** in-horizon kWh SHALL be the planned scheduled energy plus the planned surplus energy
- **AND** post-horizon kWh SHALL be the solved deferred tier energy, attributed to the tier's slots cheapest-first and summed per date

#### Scenario: Planned per-day basis and legacy fields
- **WHEN** a `planned_by_day` entry is returned
- **THEN** its basis SHALL be `known` when every slot of that day up to the deadline has a published price, otherwise `estimated`
- **AND** the legacy fields `daily_quota_kwh` and `quota_schedule` SHALL NOT be returned
