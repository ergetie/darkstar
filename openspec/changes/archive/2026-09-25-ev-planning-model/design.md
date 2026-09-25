## Context

EV goal planning today runs in two stages:

1. **Pre-solver split** (`planner/pipeline.py` `_compute_daily_ev_quota` → `planner/strategy/multi_day_planner.py`). It only runs when the deadline is more than 24 h away and a forecast exists. It splits `required_kwh` across calendar days using inverse average-price weights, a 10% minimum on every non-final day, and per-day caps of `max_power_kw × hours`, then consolidates chunks.
2. **Kepler** (`planner/solver/kepler.py` ~667-717). For every in-horizon day it adds `scheduled + surplus ≤ quota`, and it sets `effective_required = min(required, Σ in-horizon quotas)` with a soft shortfall penalty (default 50 SEK/kWh).

When the deadline sits inside the known-price horizon, (1) and (2) together fix exactly how much each day gets, and the optimiser has no freedom left. That is the root cause of the 2026-09-25 prod plan, which charged 6.58 kWh on an expensive day while the next day was cheap and fully published.

The Kepler horizon equals the published Nordpool prices: today, plus tomorrow after about 13:00. Forecasts (`price_forecasts.spot_p50`, D+0..D+7) exist beyond it. `get_known_spot_by_slot` (`known-price-precedence`) already tells published slots apart from forecast slots.

Charger power comes from a user-typed `max_power_kw`, independent of `max_current_a` / `phases`:
- `derive_min_power_kw` uses `min_current_a × 230 × phases`;
- the executor's `planned_kw_to_amps` divides by `230 × active_phases`.

On prod, `max_power_kw: 11` but 12 A × 3 × 230 V = 8.3 kW, so the planner overestimates delivery by about 33%.

## Goals / Non-Goals

**Goals:**
- A single EV goal model that is correct for these goal shapes:
  - the deadline is inside the horizon;
  - the deadline is beyond it (D+1 before the auction, D+3, D+7);
  - the forecast is unavailable.
- Inside the known horizon, the optimiser alone decides when to charge.
- Beyond it, the optimiser defers only when the forecast (plus a user risk margin) is cheaper. The decision re-evaluates on every re-plan as prices get published.
- A physical minimum in the horizon only when the post-horizon window cannot finish the goal.
- One charger-power model shared by the planner, preflight, load service and executor.
- The UI shows what the system plans per day, and whether each number rests on real or forecast prices.

**Non-Goals:**
- Re-plan on goal save, pending UX, and HA goal semantics (`ev-goal-lifecycle-feedback`).
- EV cost reporting, stale SoC, per-charger delivered, and cleanup (`ev-cost-accuracy-cleanup`).
- Load-balancer degradation and 1-phase fallback (`load-balancer-graceful-degradation`).
- Water-heater multi-day logic. It does not use `MultiDayPlanner`.

## Decisions

### D1. Replace the quota with a tiered deferral term inside Kepler

For each plugged charger with a goal, the soft requirement becomes:

```
delivered_in_horizon + Σ_k deferred_k + shortfall ≥ required_kwh
0 ≤ deferred_k ≤ cap_k                    (one tier per post-horizon price block)
cost += Σ_k deferral_price_k · deferred_k + shortfall_penalty · shortfall
```

- **Tiers** are built from the post-horizon, pre-deadline slots.
  - Each slot gets a price (forecast spot converted to an import price, see D3) and a capacity of `charger_max_kw × slot_hours`.
  - Slots are sorted ascending by price and grouped into at most `N_TIERS = 24` blocks of consecutive price rank. Each block has an energy-weighted price and a summed capacity.
  - Each block price is multiplied by `(1 + effective_margin)`, where `effective_margin` is the deadline-proximity-ramped margin from D5.
- **Why tiers instead of one scalar value:**
  - Deferring 2 kWh can use the single cheapest night; deferring 20 kWh needs dearer slots too. A single average would under-price large deferrals.
  - Ascending tier prices keep the LP convex, so the solver fills cheaper tiers first without extra binaries.
- **Physical minimum is emergent.** `Σ cap_k` is the maximum the post-horizon window can deliver. Anything beyond it can only be met in-horizon or become shortfall at 50 SEK/kWh. No separate constraint is needed.
- **Deadline inside the horizon:** there are no tiers, so the requirement is the original one. This covers the short goal with no special casing.

**Alternatives considered:**
- *Fix the quota* (cheapest-first allocation, caps only on post-horizon days). This still pre-decides energy outside the optimiser and ignores intra-day price shape, battery interplay and surplus. Rejected.
- *Scalar terminal value.* Simpler, but mis-prices large deferrals (above). Rejected.
- *Extend Kepler's horizon with forecast slots.* It would double or triple the MILP size, and forecast slots would leak into the executed plan. Rejected.

### D2. Known-vs-forecast classification is per slot, from the known-price resolver

- The horizon end is the end of the last slot Kepler plans, i.e. the last published price.
- Post-horizon slots take the forecast `spot_p50` from `price_forecasts` (latest issue). Any slot `get_known_spot_by_slot` reports as published outside Kepler's slot list uses the published value instead; this is defensive, as Kepler normally includes every published slot.
- This replaces `fetch_price_floor_inputs` daily averages for EV. The safety-floor consumer of that function is unaffected.

### D3. Deferral prices use the same tariff as in-horizon prices

The forecast is spot only; `export_price_sek_kwh` is also pure spot. Tiers therefore convert spot to import price with the existing `backend/core/prices.py` `calculate_import_export_prices` (grid fee, energy tax, VAT), so in-horizon and deferred energy are compared like for like. Comparing raw spot to import prices would bias the solver heavily toward deferral.

### D4. Forecast-unavailable fallback is conservative, never silent

When post-horizon slots have no forecast:
- **Price:** each missing slot takes the trailing 14-day average realised import price from `slot_observations`, times `(1 + effective_margin)`.
- **No history:** if that is also unavailable, the maximum in-horizon import price is used, which effectively means "don't defer".
- **Logging:** the pipeline logs a warning and records `deferral_price_source ∈ {forecast, trailing_average, horizon_max}` per charger in the persisted state and diagnostics.

The system therefore never front-loads a D+5 goal just because the forecast fetch failed, and never gambles blindly either.

### D5. Risk margin: user base plus deadline-proximity ramp

The risk margin has a user-set base and grows as the deadline approaches (decided by the user on 2026-09-25).

- **Settings** (EV settings tab, global for all chargers; per-charger is YAGNI):
  - `ev_planning.deferral_risk_margin_percent`: base margin, default 12, range 0–100.
  - `ev_planning.deferral_risk_margin_max_percent`: margin reached at the deadline, default 50, range base–200. Setting it equal to the base disables the ramp.
  - `ev_planning.deferral_risk_ramp_hours`: how far before the deadline the ramp starts, default 48, range 1–168.
- **Formula**, evaluated once per charger per planner run, with `h` = hours from now to the goal's deadline:

  ```
  ramp = clamp(1 − h / ramp_hours, 0, 1)
  effective_margin = base + (max − base) × ramp
  ```

  With the defaults: 12% when the deadline is 48 h or more away, 31% at 24 h, 50% at the deadline. The ramp is linear and computed per run, so every re-plan tightens it as the deadline gets closer.
- **Why per goal, not per tier:** the risk is the goal ending up short or paying a panic price. That grows with how little time is left to recover from a bad forecast, which is a property of the goal. A per-tier ramp would make tiers near the deadline dearer than earlier ones at the same forecast price, which is the same signal applied twice.
- **Where it applies:** the tier prices (D1) and the trailing-average fallback (D4). It has no effect when the deadline is inside the horizon, because there are no tiers.
- A higher margin means more charging now and less reliance on forecasts.
- The pipeline logs and persists `effective_margin_percent` per charger next to `deferral_price_source`, so the ramp is visible.
- `kepler.ev_shortfall_penalty_sek_per_kwh` (default 50) is surfaced in the EV settings tab as an advanced field.

### D6. Charger power is derived, not typed

- `type: current`:
  - `max_kw = max_current_a × len(phases) × V / 1000`;
  - `min_kw = min_current_a × len(phases) × V / 1000 × 1.01` (the existing rounding margin);
  - `V = system.grid.nominal_voltage_v` (default 230, see D9).
- `type: binary`: `rated_power_kw`, which must be > 0. Voltage, amps and phases are never used.
- **Shared helper.** A single `charger_power_limits(cfg, voltage)` lives in a shared module (`backend/core/ev_power.py`), used by:
  - the adapter, the pipeline diagnostics and status helpers, and preflight;
  - `backend/loads/service.py` and the executor (`planned_kw_to_amps` takes the voltage from the same source).
- **Migration** (`backend/config_migration.py`):
  - current type: drop `max_power_kw` and `nominal_power_kw`, logging the derived kW so the user sees the change;
  - binary type: rename `max_power_kw` (or `nominal_power_kw`) to `rated_power_kw`.
  - Validation rejects a current charger missing `max_current_a` or `phases`, and a binary charger with `rated_power_kw ≤ 0`. This replaces the existing "missing max_power_kw" error in `planner/errors.py`.
- Phase switching (1-phase) reduces the real maximum. The planner plans at the configured phase count. Change 4 handles runtime degradation, and re-plans correct the plan. **Known limitation, accepted by the user on 2026-09-25:** while the balancer holds 1-phase, the plan can under-deliver until the next re-plan. It is out of scope here; the evaluation is tracked in `docs/BACKLOG.md`.

### D7. Planned per-day estimate replaces `quota_schedule`

After the solve, the pipeline builds `planned_by_day: [{date, kwh, basis}]` per charger:
- **In-horizon days:** kWh = scheduled + planned surplus from the Kepler result. Planned surplus counts toward the goal (decided by the user on 2026-09-25).
- **Post-horizon days:** kWh = the solved `deferred_k` distributed back to the slots of each tier, cheapest first, then summed per date.
- **Basis:** `known` if every slot of that day up to the deadline had a published price, else `estimated`.

The state file and `GET /api/ev/chargers` expose `planned_by_day`; `daily_quota_kwh` and `quota_schedule` are removed. The EV card renders the days up to the deadline as chips: solid for `known`, faded with an "est." label for `estimated`.

### D8. Remove `MultiDayPlanner` and the >24 h gates

- Delete `planner/strategy/multi_day_planner.py` and its tests.
- Delete `_compute_daily_ev_quota` and `_max_daily_kwh_for_deadline`, the >24 h checks at `pipeline.py` ~1440/~1494, and the `quota_by_day` path in Kepler.
- The `min_chunk` consolidation disappears with the quota. Kepler already models semi-continuous current chargers and equality-power binary chargers natively.

### D9. One nominal grid voltage, and no silent charger disablement

Follow-up decided by the user on 2026-09-25.

- **Single voltage.** `system.grid.nominal_voltage_v` (default 230 V, EU standard) sits next to `system.grid.main_fuse_a` and replaces `load_balancing.nominal_voltage_v` (previously 220, deliberately biased low). `backend/core/ev_power.nominal_voltage_v()` reads it, and it feeds:
  - EV power derivation (D6), preflight, load service and pipeline diagnostics;
  - the executor: `ExecutorConfig.ev_nominal_voltage_v` (planned kW→A, manual-charge kW, measured draw from the disaggregator, per-phase W→A) and `LoadBalancingConfig.nominal_voltage_v`;
  - `executor/ev_surplus.py` surplus amps and 1-/3-phase minimum-power thresholds, which previously hard-coded 230.
  Per-phase `input_sensors.grid_voltage_l1..l3` still take precedence in the load balancer for real-time control. The settings field lives in the System profile next to the grid limits, validated to 100–260 V.
- **Migration.** `_migrate_nominal_voltage` moves the legacy value as-is (the new key wins if both exist), runs before the EV power migration (whose log uses the voltage), is idempotent and reuses the backup-before-write path. A legacy value that is the old template default of 220 is carried over unchanged; the user can set 230 in settings.
- **Missing phases.** A current charger without `phases` stays disabled, but visibly: `charger_disabled_reason()` in `ev_power.py` returns a code (`missing_phases`, `missing_max_current`, `missing_rated_power`) and a message naming the charger by its configured `name` ("Configure phases for <name> to enable planning"). The load service registers the code, `GET /api/ev/chargers` returns the message as `disabled_reason`, the EV card shows it, migration logs a warning, and the charger editor marks phases required (pre-filled L1/L2/L3 for new chargers) and blocks saving without them.

## Risks / Trade-offs

- **[Forecast systematically too cheap → repeated deferral, then an expensive catch-up near the deadline]** → Mitigations:
  - the risk margin, which ramps up as the deadline approaches (D5);
  - tiers are recomputed every re-plan;
  - deferral is only possible into slots before the deadline;
  - capacity caps force in-horizon charging when the tail is too short;
  - `deferral_price_source` and per-day `basis` make it visible.
- **[Assumes the car stays plugged until the deadline]** → Consistent with the goal semantics (a ready-by implies plugged). Change 2 surfaces the plan while unplugged, with a plug-in reminder.
- **[MILP size]** → At most 24 extra continuous variables per charger; negligible.
- **[Config migration surprises users with a lower kW]** → Log the derived value, and show a derived read-only "max power" in the charger editor.
- **[API field removal breaks external consumers of `quota_schedule`]** → Only the bundled frontend consumes it; it is updated in the same change.
- **[Deferral tiers ignore intra-day battery/house interplay post-horizon]** → Accepted: those slots are re-optimised properly once published.

## Migration Plan

1. Ship the config migration first in the same release. It is idempotent and runs at startup like the existing migrations.
2. State-file reader tolerates old `quota_schedule` / `daily_quota_kwh` keys and ignores them. The writer emits `planned_by_day` only.
3. Rollback: revert the release. The old code reads `max_power_kw`, so migration must keep a backup of the pre-migration config; the existing migration backup mechanism is reused.

## Open Questions

- Is `N_TIERS = 24` the right granularity for D+7 goals? It gives about 4 slots per tier per day at 7 days. Tune during implementation using test cases.

Resolved on 2026-09-25: planned surplus counts toward the goal; the risk margin ramps up toward the deadline (D5); runtime 1-phase under-delivery is an accepted known limitation, to be evaluated later.
