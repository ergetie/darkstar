## Why

EV goal planning splits the required energy into fixed per-day quotas before the optimiser runs: inverse-price weights, a 10% minimum on every non-final day, and per-day caps. Once the deadline is inside the known-price horizon, those caps plus the capped soft requirement decide exactly how much charging each day gets. On prod on 2026-09-25, a 22.2 kWh goal due 2026-09-26 23:00 was forced to charge 6.58 kWh on the expensive current day, even though every price up to the deadline was published and the next day was much cheaper. The same split also misbehaves in other situations:
- A deadline less than 24 h away but beyond the known prices gets no quota, so all charging is crammed into the known window.
- A failed forecast fetch silently disables spreading, so everything is front-loaded.
- Energy that doesn't fit into whole chunks is silently dropped.

Separately, the planner's charging-power model comes from a free-typed `max_power_kw` (11 kW on prod). The charger's configured amps and phases actually limit it to 8.3 kW, and to 6.9 kW now at 10 A. The planner therefore consistently books too few hours and under-delivers.

## What Changes

- **BREAKING (behaviour):** remove the pre-solver per-day energy split (`MultiDayPlanner`), the per-day quota caps in Kepler, and the "cap the requirement at the sum of in-horizon quotas" rule.
- **Deadline inside the known horizon:** when every slot up to the deadline has a published price, Kepler optimises the goal directly: the soft requirement, no quota, and no future-value term.
- **Deadline beyond the known horizon:** Kepler gets a *deferral value*, a per-kWh price for energy not delivered inside the horizon.
  - It is derived from the forecast prices of the cheapest post-horizon, pre-deadline slots needed to finish the goal, marked up by a user-configurable risk margin (default 12%).
  - Kepler charges inside the horizon only where that is cheaper than the deferral value, or where energy is free (surplus PV).
- **Hard in-horizon minimum** only when the post-horizon window cannot physically deliver the remainder: plug-in hours × charger power up to the deadline.
- **One code path** for all goal shapes:
  - short (deadline in horizon), long (D+3 and beyond), and mixed (deadline tomorrow before the day-ahead auction);
  - a deadline less than 24 h away but past the horizon;
  - forecast unavailable. A conservative fallback is used and the planner does not silently front-load.
  - This replaces the triple ">24 h" gate.
- **BREAKING (config):** charging power is derived from `max_current_a` × phase count × voltage for `type: current` chargers. `max_power_kw` is retired for current chargers and is migrated/ignored with a warning. Binary chargers keep an explicit rated power, renamed to `rated_power_kw` and migrated from `max_power_kw`. Planner, preflight, load service, diagnostics and executor kW↔A conversion all use the same derivation.
- **EV card per-day estimate:** "Upcoming Daily Quotas" becomes a **planned per-day estimate**. Each day shows the planned kWh and is flagged `known` when all its slots have published prices, otherwise `estimated`. The API field `quota_schedule` is replaced by `planned_by_day`.
- **Settings:** the EV shortfall penalty (`kepler.ev_shortfall_penalty_sek_per_kwh`) and the new deferral risk margin are exposed in the settings UI.

## Capabilities

### New Capabilities
- `ev-deferral-value`: covers the following:
  - classifying the time up to the deadline into known and forecast time;
  - computing the per-kWh deferral value (and a fallback when the forecast is missing);
  - the physical in-horizon minimum;
  - the planned per-day estimate with known/estimated flags.
- `ev-charging-power`: derives a single charger-power model from amps × phases × voltage (current type) or rated power (binary type), and migrates it from `max_power_kw`.

### Modified Capabilities
- `multi-day-deferral-controller`: all requirements are removed; the `MultiDayPlanner` is deleted (EV was its only consumer).
- `ev-target-charging`: the Kepler soft requirement no longer uses per-day quota caps; the deferral value replaces the multi-day quota; the API exposes `planned_by_day` instead of `daily_quota_kwh` / `quota_schedule`; the penalty is configurable in the UI.
- `ev-surplus-charging`: the "surplus counts toward the daily quota" requirement is removed (there is no quota any more).
- `ev-dashboard-card`: the EV tab shows the planned per-day estimate with known/estimated flags instead of quotas.
- `per-device-ev-scheduling`: per-device config replaces `max_power_kw` with derived power (current) or `rated_power_kw` (binary). The invalid-power disablement is keyed on derived power.
- `ev-current-control`: the kW→A conversion uses the configured nominal voltage from the shared power helper instead of a hard-coded 230 V.

## Impact

- **Planner:** `planner/pipeline.py`:
  - EV goal block ~1400-1530;
  - functions to remove or replace: `_compute_daily_ev_quota`, `_max_daily_kwh_for_deadline`, `fetch_price_floor_inputs` usage, `_persist_ev_multi_day_state`, and the status/diagnostics helpers that use `max_power_kw`;
  - `planner/strategy/multi_day_planner.py` is deleted, along with `tests/planner/test_multi_day_planner.py`.
- **Solver:** `planner/solver/kepler.py`:
  - remove the quota caps and effective-required;
  - add the deferral-value objective term and the physical minimum;
  - `planner/solver/types.py` (`EVChargerInput`) and `planner/solver/adapter.py` (`derive_min_power_kw`, `build_ev_charger_inputs`).
- **Power consumers:** `planner/preflight.py`, `backend/loads/service.py`, `planner/errors.py`, and the executor kW↔A conversion (`executor/engine.py`, `planned_kw_to_amps`).
- **Config:** `backend/config_migration.py`, `config.default.yaml`, and the config validation in `backend/api/routers/config.py`.
- **API:** `backend/api/routers/ev.py` (`GET /api/ev/chargers` field change) and the state file `data/ev_multi_day_state.json` (field rename).
- **Frontend:**
  - `frontend/src/components/EVChargingCard.tsx` (plus its tests) and `frontend/src/lib/api.ts`;
  - settings: `frontend/src/pages/settings/types.ts` (EV and advanced Kepler fields) and the charger editor.
- **Out of scope** (separate changes):
  - re-plan on goal save and pending UX;
  - EV cost reporting, stale-SoC handling, and cleanup;
  - load-balancer degradation.
