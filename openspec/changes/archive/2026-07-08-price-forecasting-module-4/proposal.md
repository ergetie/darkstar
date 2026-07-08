## Why

Darkstar's EV charging is driven by hand-tuned "penalty levels" (incentive buckets): a per-SoC-band willingness-to-pay in SEK/kWh. Stabilization-review **Finding #1 (S1)** confirmed this model is wrong for what users actually want:

- The default is **empty**, so out of the box the EV **silently never charges** from surplus PV — it exports instead (worked example in Finding #1).
- To make it work the user must reason about spot vs import prices and set a value that sits between them — solver math no normal user can tune.
- Even when tuned, a willingness-to-pay can **never guarantee** the car reaches a usable charge by departure. It only ever says "charge if it's worth it", never "you must reach X% by time T".

What users (and a second user requesting "leave it on so the heater can run at 07:15") actually want is a **goal**: *"have the car at X% by this time"* — and then have the system charge as cheaply as possible, preferring free solar, exactly like the home battery already does. This change replaces the penalty-level model with that goal-based model. (Multi-day deferral — the original Module 4 scope — survives as an automatic behaviour, not a user mode.)

## What Changes

- **New per-charger goal:** `target_soc_percent` + `ready_by` time + optional `repeat` (daily / chosen weekdays / every N days / **none** = a one-off specific date). One concept — a specific date is just "no repeat", **not** a separate mode.
- **Requirement, not incentive:** Kepler gains a **soft "reach target SoC by the ready-by time" constraint** (a large shortfall penalty, kept soft so an unreachable target never makes the solve infeasible — it just charges as much as it can and reports "behind"). This replaces the incentive-bucket reward term entirely.
- **Retire penalty levels** from the user-facing model. The incentive-bucket variables/rewards are removed from Kepler; the only "penalty" left is the internal, auto-set shortfall penalty (never user-tuned).
- **Excess-PV self-consumption priority is owned by the already-shipped `excess_pv.priority[]` list** (the `excess-pv-priority-dispatch` change). The home battery is implicitly first via `soc_threshold_percent`; users wanting EV-first move the `ev` entry up that list in the existing Settings editor. **No new tie-break code, no `charge_priority` field in this change.**
- **`keep_on_after_target`** (default false): once the target is met, leave the charger switch enabled through the ready-by time so the car can pre-condition / run its heater. (Executor behaviour; consumed by Module 5's switch control.)
- **Multi-day is automatic:** when the ready-by date is several days out and a 7-day price forecast exists, the reusable `MultiDayPlanner` spreads the required energy onto the cheaper days; when it is near, Kepler optimises within the known Nordpool horizon. **The core feature needs only the day-ahead prices the planner already has — it is NOT gated behind `price_forecast.enabled`.** The 7-day forecast (Module 1) is an optional enhancement for multi-day spreading only.
- **Read-only state API** (`GET /api/ev/chargers`): per-charger live status + goal + progress + on-track/behind status for Module 5's UI.

## Capabilities

### New Capabilities
- `ev-target-charging`: The goal-based EV model — `target_soc_percent` + `ready_by` + `repeat` config, the soft target-by-time requirement in Kepler (replacing incentive buckets), `keep_on_after_target`, and the read-only `GET /api/ev/chargers` state API. Surplus absorption is **not** re-implemented here — it is owned by the existing `excess-pv-priority-dispatch` capability, which is gated on `type: current` chargers and on the charger being listed in `excess_pv.priority[]`.
- `multi-day-deferral-controller`: The reusable, load-agnostic `MultiDayPlanner` engine that spreads a required energy amount across the days until a far ready-by date using a 7-day price forecast. Invoked automatically; degrades gracefully when no forecast exists.

### Modified Capabilities
- `per-device-ev-scheduling`: Per-charger config changes from `departure_time` + `penalty_levels` to `target_soc_percent` + `ready_by` + `repeat` (+ optional `ready_by_date`, `keep_on_after_target`). `penalty_levels` is retired. `departure_time` is accepted as a deprecated alias for `ready_by` for one release.

## Impact

- **Solver** (`planner/solver/kepler.py`, `adapter.py`, **`planner/solver/types.py`** — *not* `planner/inputs/types.py`, which has no EV types): remove the incentive-bucket variables + reward term; add a soft "delivered EV energy ≥ required_kwh by deadline" constraint with a shortfall penalty (default 50.0 SEK/kWh, configurable via `kepler.ev_shortfall_penalty_sek_per_kwh`); pass `required_kwh`, `deadline`, `daily_quota_kwh` on `EVChargerInput`. **No excess-PV self-consumption priority term is added** — that is owned by the existing `excess_pv.priority[]` machinery from `excess-pv-priority-dispatch` (battery implicitly first via `soc_threshold_percent`; EV surplus only for `type: current` chargers listed in the priority list).
- **Planner** (`planner/pipeline.py`, new `planner/strategy/multi_day_planner.py` — the EV block is now at `pipeline.py:739-796`, not the `~536-593` cited in earlier drafts): resolve each charger's next ready-by datetime from `ready_by` + `repeat` (or `ready_by_date`); compute `required_kwh` from `target_soc_percent`, current SoC, and `battery_capacity_kwh`; invoke `MultiDayPlanner` when the deadline is multi-day and a forecast exists.
- **Config** (`executor/config.py`, `config.yaml`, `config.default.yaml`): new per-charger fields (`target_soc_percent`, `ready_by`, `repeat`, `n_days`, `ready_by_date`, `keep_on_after_target`); new solver-level `kepler.ev_shortfall_penalty_sek_per_kwh` (default 50.0, advanced); retire `penalty_levels` (a raw YAML key consumed only at `adapter.py:147-155` — not a dataclass field); ship a sensible default goal so a configured charger charges out of the box.
- **API** (`backend/api/routers/ev.py`): new read-only `GET /api/ev/chargers` (live HA sensor data + goal + progress + status). Contract consumed by Module 5.
- **Data:** `required_kwh` derives from `slot_observations` EV energy + live SoC; transient multi-day state persisted to `data/ev_multi_day_state.json`. No DB schema change. (`charge_priority` is intentionally **not** persisted — it does not exist in this change.)
- **Binary-charger surplus limit (accepted):** `type: binary` chargers still receive the deadline-target scheduled-charging benefit (cheapest slot prices by ready-by), but **cannot absorb surplus PV** — fractional surplus absorption requires continuous current control, gated at `kepler.py:309` (`control_type == "current"`). This is an accepted limitation; no special code path is added.
- **Relations:** resolves stabilization-review **Finding #1 (S1)**; Module 5 adds the UI + HA entity sync; supersedes the prior penalty-level EV economics. Optional dependency on Module 1 (price forecasts) for multi-day spreading only.
- **No breaking behaviour for a correctly configured charger**; users still on `penalty_levels` get a one-release deprecation path + migration to an equivalent goal.
