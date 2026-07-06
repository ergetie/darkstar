## Context

The Kepler MILP (`planner/solver/kepler.py`) schedules each enabled water heater with per-device binary variables `water_heat[d][t]` (heating on/off) and `water_start[d][t]` (block start). Today it enforces, per device:

- a per-day **daily-minimum energy** constraint (`min_kwh_per_day`), soft-penalized by `water_reliability_penalty_sek`;
- a **block-duration** breaker (`max_block_hours`), soft-penalized by `water_block_penalty_sek`;
- a **hard minimum spacing** between block starts (`min_spacing_hours`, from `water_min_spacing_hours`);
- a **block-start** penalty (`water_block_start_penalty_sek`).

All four penalty weights are derived from `comfort_level` via `COMFORT_MAP` (`adapter.py:277-314`). There is **no term that bounds the time between heatings** — `water_heating_max_gap_hours` (`types.py:73`, set from `max_hours_between_heating` at `adapter.py:453`) is never read by `kepler.py`, and `gap_violation_penalty` is hardcoded `0.0` (`kepler.py:557`) and added twice (`kepler.py:632-633`). Historical arc verified in git: hard sliding-window gap (K17) → soft gap (K18) → disabled for solve-time (K21/PERF1) → **linear discomfort counter** (`af214dc8`, O(T), the intended performance-safe replacement) → **lost in same-day refactor `b650208d`**.

Config finding #15: the global `water_heating.*` penalty keys (`reliability_penalty_sek`, `block_start_penalty_sek`, `spacing_penalty_sek`, `block_penalty_sek`) are read by nothing in non-test source — `COMFORT_MAP` supplies the real values. They mislead the operator (e.g. `reliability_penalty_sek: 1000` while the solver uses 15).

Economics finding #16: in the objective, `slot_export_revenue = grid_export[t] * (export_price − export_threshold)` and `slot_curtailment_cost = curtailment[t] * curtailment_penalty` (`kepler.py:500-523`). When effective export price ≤ 0, exporting is free-or-worse but curtailing costs 0.1 SEK/kWh, so the solver exports at a loss.

## Goals / Non-Goals

**Goals:**
- Make `max_hours_between_heating` a real, honored gap ceiling via a soft, performance-safe (O(T)) discomfort penalty.
- Make `comfort_level` scale the *strength* of gap protection (Design A: weight only, not the ceiling).
- Make the config + settings UI truthful: only the controls that actually work remain.
- Stop the solver from paying to export PV at non-positive prices.

**Non-Goals:**
- No change to daily-minimum, spacing, block-start, or block-duration behavior (only additive gap term).
- No change to executor, recorder, ML, vacation mode, or bulk mode.
- No new user-facing "ceiling per comfort level" mapping (Design B, rejected).
- No attempt to seed the discomfort counter from real "hours since last heat" beyond what is already available (see Decision 4).

## Decisions

### Decision 1 — Linear discomfort counter, per-device, with a deadband (Design A)
Reinstate the `af214dc8` formulation, adapted to the current per-device model and extended with a deadband so gaps up to the ceiling are free.

Per enabled heater `d`, add two non-negative variable families:
- `discomfort[d][t]` — "hours since last heating" accumulator;
- `gap_over[d][t]` — the portion of `discomfort` beyond the ceiling (the only penalized part).

Constraints, for `t` in `range(T)` with `duration = slot_hours[t]`, big-M `M = 100.0`, and `deadband = config.water_heating_max_gap_hours`:
```
# accumulate hours; reset toward 0 when heating is ON (M forces the reset)
if t == 0:
    discomfort[d][t] >= duration - water_heat[d][t] * M
else:
    discomfort[d][t] >= discomfort[d][t-1] + duration - water_heat[d][t] * M
# deadband: only the overshoot beyond the ceiling is penalized
gap_over[d][t] >= discomfort[d][t] - deadband
```
Objective term (added to the existing `prob +=` block, replacing the doubled dead `gap_violation_penalty` lines):
```
+ (pulp.lpSum(gap_over[d][t] for d in gap_over for t in range(T)) * config.water_gap_penalty_sek
   if water_enabled and gap_penalty_active else 0.0)
```
where `gap_penalty_active = config.water_heating_max_gap_hours > 0 and config.water_gap_penalty_sek > 0`.

This is O(T) per heater (no sliding windows), matching the performance-safe design that was lost.

### Decision 2 — `comfort_level` scales only the weight
Add one column, `water_gap_penalty_sek`, to `COMFORT_MAP` in `adapter.py`, alongside the existing `water_reliability_penalty_sek` etc. Wire it into `KeplerConfig.water_gap_penalty_sek`. The **ceiling** (`water_heating_max_gap_hours`) is untouched by comfort level — it stays whatever `max_hours_between_heating` is set to. Proposed weights (SEK per hour of overshoot), scaling in the same spirit as the reliability column (2 → 7 → 15 → 30 → 300):

| comfort_level | water_gap_penalty_sek |
|---|---|
| 1 Economy | 0.5 |
| 2 Balanced | 2.0 |
| 3 Neutral | 5.0 |
| 4 Priority | 15.0 |
| 5 Maximum | 50.0 |

These are a starting point tuned to the same order of magnitude as import price × kWh so the solver trades a top-up heat against the price saving; the implementer SHALL confirm behavior on a representative day (see tasks) and may adjust, keeping monotonic increase.

**Representative-day check (task 7.3, done):** simulated a 24h day with a realistic Nordpool-shaped price curve (cheap 0.27-0.45 SEK/kWh overnight, peaks to 2.10 SEK/kWh evening), one 3kW heater, `min_kwh_per_day=6.0`, `max_hours_between_heating=8`, `comfort_level=3`. Without the gap penalty the solver bunched all heating into the single cheapest window, leaving a ~20h unresolved tail. With `water_gap_penalty_sek=5.0` the solver split into 2 blocks using exactly the 6.0 kWh daily minimum (no extra cycling), max gap 8.5h (ceiling + one slot). No weight adjustment needed at Level 3.

### Decision 3 — Reuse the existing global deadband/enable plumbing
Use the global `config.water_heating_max_gap_hours` as the deadband for all heaters (it is already set from `max_hours_between_heating` and already forced to `0.0` when `enable_top_ups: false` at `adapter.py:453-457` and in vacation mode at `pipeline.py:682`). Gating on `> 0` therefore preserves both the bulk-mode and vacation-mode disables **for free**. Multi-heater installs share this single ceiling, consistent with the current single-value plumbing; per-heater ceilings are out of scope.

### Decision 4 — Initial condition: start the counter at 0
At the horizon start `t == 0`, `discomfort` starts from 0 (matching `af214dc8`). No reliable "hours since last heat" input exists (`heated_today_kwh` is energy, not time). Because the planner re-runs hourly on a rolling horizon, a real over-gap becomes visible and penalized within `deadband` hours. This is an accepted simplification; seeding from a future `hours_since_last_heat` input is explicitly out of scope.

### Decision 5 — Remove the fictional config keys and dead field
Delete from `config.default.yaml`: `water_heating.reliability_penalty_sek`, `.block_start_penalty_sek`, `.spacing_penalty_sek`, `.block_penalty_sek`. Delete the corresponding UI entries in `frontend/src/config-help.json` and `frontend/src/pages/settings/types.ts`. Delete the dead `KeplerConfig.water_comfort_penalty_sek` field (`types.py:74`) and the two doubled `gap_violation_penalty` objective lines (`kepler.py:632-633`) and the `gap_violation_penalty` initialization (`kepler.py:557`). Existing user `config.yaml` files may still contain these keys; extra keys are ignored by the loader, so no migration is required (a strip-on-migrate is optional and out of scope).

### Decision 6 — Curtailment/export tiebreak (#16)
In `kepler.py`, only credit curtailment as free (and prefer it) when exporting would cost money. Concretely, make the curtailment penalty conditional on the effective export price: when `effective_export_price <= 0`, curtailment SHALL cost 0 (or less than exporting) so the solver curtails instead of paying to export; when `effective_export_price > 0`, keep the existing `curtailment_penalty_sek` so genuine exports are still preferred over waste. Equivalent framing: set the per-slot export floor to the break-even `max(effective_export_price, 0)` so non-positive-priced export is never chosen over curtailment. The implementer SHALL pick whichever is cleanest in the current objective structure and cover it with the #16 scenario.

## Risks / Trade-offs

- **Weight tuning:** if `water_gap_penalty_sek` is too high the solver over-heats (cost/wear up); too low and gaps still stretch. Mitigated by the representative-day check task and monotonic, order-of-magnitude-anchored defaults. The runtime `command_success`/plan monitors from stabilization-review-2 do not cover comfort, so validation is via solver tests + one production soak.
- **Solve time:** two extra O(T) variable families per heater. Negligible vs the existing per-slot battery/EV variables; the sliding-window versions (the ones that were killed for performance) are *not* reintroduced.
- **Spacing vs gap tension:** hard `water_min_spacing_hours` (floor, e.g. 4 h) and the gap ceiling (e.g. 8 h) define a feasible cadence band; floor < ceiling so no infeasibility. If a user sets spacing ≥ ceiling the gap term can be unsatisfiable-but-soft (penalty only, never infeasible) — acceptable, and worth a validation note.
- **#16 scope creep:** the money impact is trivial (−0.53 SEK across 58 slots); it is included only because it lives in the same objective. Kept to a single conditional to avoid touching export-floor logic.
