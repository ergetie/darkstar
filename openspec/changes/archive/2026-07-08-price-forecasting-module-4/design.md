## Context

Stabilization-review **Finding #1 (S1)** confirmed that EV charging exports surplus PV instead of charging because the only thing that values EV charging in the Kepler objective is the configured incentive-bucket reward (`ev_bucket_charged · value_sek`), which:
- is **zero by default** (`penalty_levels: []`) → the EV never charges, surplus is exported;
- only wins against export when the user-set `value_sek` exceeds the spot export price, and only wins against grid when it exceeds the import price — i.e. it is a hand-tuned reservation price;
- can never *guarantee* a charge level by a time — it is a willingness-to-pay, not a requirement.

The home battery does not work this way: it simply charges from the cheapest energy (and free PV) toward its targets. This change makes the EV behave the same, driven by a user **goal** instead of a price knob.

Key existing code:
- `planner/pipeline.py`: per-charger EV deadline calculation, now at `~739-796` (the `~536-593` region cited in earlier drafts is now occupied by the Module-3 price-floor wiring).
- `planner/solver/kepler.py`: incentive-bucket variables are at `:124-149` and `:233-264`; bucket reward term at `:768-777` (the `:203-234` / `:642-651` ranges cited in earlier drafts are stale). Per-device `ev_energy[d][t]` variables and deadline constraints are around `:428-432`.
- `planner/solver/types.py:33-48`: `EVChargerInput` lives here (the design previously cited `planner/inputs/types.py`, which has no EV types — only `SlotData`, `PlannerInput`, `StrategyContext`, `BatteryConfig`).
- `planner/solver/adapter.py:147-155`: maps `penalty_levels` (a raw YAML key — **not** an `EVChargerDeviceConfig` dataclass field) → `IncentiveBucket`.
- `executor/config.py:142-172`: `EVChargerDeviceConfig` (`departure_time`, `switch_entity`, `type`, `current_entity`, …). It has no `penalty_levels` field.

## Goals / Non-Goals

**Goals:**
- Replace the penalty-level EV economics with a goal-based model (`target_soc_percent` by `ready_by`, optionally repeating).
- Make a configured charger charge correctly out of the box (sensible default goal; no price knowledge required).
- Spread charging across cheaper days automatically when the ready-by date is far and a forecast exists.
- Leave excess-PV self-consumption ordering to the existing `excess_pv.priority[]` machinery — **do not** add a parallel priority switch in this change.
- Keep the engine usable by the executor's switch control (`keep_on_after_target`) and by Module 5's UI/HA layer.

**Non-Goals:**
- No UI or HA entity sync here (Module 5).
- No V2G / EV-to-house discharge.
- No per-band willingness-to-pay (penalty levels are retired, not re-skinned).
- The `MultiDayPlanner` stays load-agnostic (no EV-specific logic inside it).

## Decisions

### D1 — Goal model: target SoC + ready-by time + optional repeat (one concept)
Per charger the user sets `target_soc_percent`, a `ready_by` time (`HH:MM`), and a `repeat` rule. `repeat ∈ {daily, weekdays, weekends, every_n_days, none}`. With `repeat: every_n_days` the user also sets `n_days` (int, the cycle length in days). With `repeat: none` the user also sets `ready_by_date` (a one-off specific date). **A specific date is just "no repeat" — there is no separate "daily vs multi-day" mode** (the prior Module 4/5 mode dropdown is removed). The pipeline resolves the *next* ready-by datetime from these fields each run.

### D2 — Requirement replaces incentive: soft "reach target by deadline" constraint
The incentive-bucket variables and the `Σ ev_bucket_charged · value_sek` reward are **removed** from Kepler. In their place, for each plugged charger with a goal:
```
delivered_kwh + shortfall[d]  >=  required_kwh        # soft
objective += shortfall[d] * EV_SHORTFALL_PENALTY      # default 50.0, configurable
```
where `delivered_kwh = Σ ev_energy[d][t]` over slots up to the deadline. **Soft on purpose:** if the car physically cannot reach the target in time (short window / low power), the solve stays feasible and `shortfall` simply surfaces as "behind". `EV_SHORTFALL_PENALTY` defaults to **50.0 SEK/kWh** — set well above any plausible import price so the solver treats the target as near-mandatory but never charges from absurdly-priced grid beyond what the requirement needs. It is a module constant (`EV_SHORTFALL_PENALTY_DEFAULT = 50.0`) overridable via the advanced `kepler.ev_shortfall_penalty_sek_per_kwh` config key. The typical user never touches it; it exists for advanced tuning only.

### D3 — `required_kwh` derived from target SoC, not typed by the user
`required_kwh = max(0, (target_soc_percent − current_soc_percent)/100 · battery_capacity_kwh) − energy_already_delivered_this_cycle`. Current SoC and battery capacity come from existing charger state/config; delivered energy from `slot_observations`. The user expresses intent in %, the system works in kWh internally.

### D4 — Excess-PV self-consumption is owned by the existing `excess_pv.priority[]` (no new code here)
The `excess-pv-priority-dispatch` change already ships the surplus-routing machinery: a priority-ordered sink list (`excess_pv.priority[]`), the home battery implicitly first via `soc_threshold_percent` (default 95%), rank-scaled rewards, EV surplus only for `type: current` chargers, mutual exclusivity with scheduled charging, and a closed-loop executor (`executor/ev_surplus.py`). **This change adds no tie-break code and no `charge_priority` field.** A user who wants EV-first surplus moves the `ev` entry up the priority list in the existing Settings editor (under Advanced → "Excess PV Dispatch"). There is no per-charger switch to duplicate or contradict that surface.
Surplus routing is also gated on the charger being listed in `excess_pv.priority[]` — without an `ev` entry pointing at it, the charger never absorbs surplus, regardless of its goal.

### D5 — `keep_on_after_target`
A per-charger boolean (default false). When the target is met, the planner keeps the charger's intended switch state ON through the ready-by time (the car draws ~0 but its heater/pre-conditioning can run). Pure flag on the plan; the executor's existing switch control (and Module 5) honour it.

### D6 — `MultiDayPlanner` survives, invoked automatically, decoupled from Module 1
The reusable, load-agnostic `MultiDayPlanner` (inverse-price daily-quota allocation, min-daily-fraction floor, power-cap redistribution, graceful no-forecast fallback) is kept. It is invoked **automatically** when the resolved deadline is more than one day out **and** a 7-day forecast is available; it returns today's `daily_quota_kwh`, which becomes an upper bound on today's EV energy in Kepler. **The core goal feature needs only the day-ahead Nordpool prices the planner already has and is NOT gated behind `price_forecast.enabled`.** Without a forecast, no quota is applied and Kepler charges as cheaply as it can within the known horizon, filling the rest as the deadline nears (the min-daily-fraction logic only applies when spreading).

### D7 — Config schema + deprecation
New per-charger fields: `target_soc_percent` (int, default 80), `ready_by` (`HH:MM`, default `"07:00"`), `repeat` (enum, default `daily`), `n_days` (int, used when `repeat: every_n_days`), `ready_by_date` (date, when `repeat: none`), `keep_on_after_target` (bool, default false). **No `charge_priority` field** — surplus ordering is owned by `excess_pv.priority[]`. **`penalty_levels` is retired**; it is not a dataclass field on `EVChargerDeviceConfig` — it is read as a raw YAML key only at `adapter.py:147-155`. Migration = delete that one comprehension plus a stale comment at `config.default.yaml:110`; if `penalty_levels` is present in a user's config it is ignored with a one-release deprecation warning and, where possible, migrated to an equivalent goal (target = highest configured `max_soc`). `departure_time` is accepted as a deprecated alias for `ready_by`. A sensible default goal ships so a configured charger charges out of the box. Additionally, the solver-level `kepler.ev_shortfall_penalty_sek_per_kwh` (float, default 50.0) is added to the `kepler:` config block for advanced tuning of the soft-target shortfall penalty.

### D8 — Read-only state API
`GET /api/ev/chargers` returns per charger: live `plugged_in` / `soc_percent` / `power_kw` (from HA, fetched on request), the goal (`target_soc_percent`, `ready_by`, `repeat`, resolved next `deadline`), `required_kwh` / `delivered_kwh` / `remaining_kwh`, today's `daily_quota_kwh` (null when not spreading), an optional `quota_schedule` (when multi-day), and a `status ∈ {on_track, behind, complete, idle}`. Transient state is written to `data/ev_multi_day_state.json` each run; the endpoint merges it with live sensors. No DB table. No `charge_priority` is returned — it does not exist on `EVChargerDeviceConfig` or `EVChargerInput`.

### D9 — Binary-charger surplus limitation (accepted)
`type: binary` chargers cannot modulate to absorb fractional surplus PV. The solver's surplus path is gated on `control_type == "current"` (`kepler.py:309`) and the executor's surplus controller skips binary chargers (`engine.py:2515`). A binary charger in `excess_pv.priority[]` is silently dropped by the solver (defense in depth; the config API rejects it upstream). **This is an accepted limitation** — binary chargers still receive the full deadline-target scheduled-charging benefit (`ev_charge[d][t] = 1` for whole slots using the cheapest day-ahead prices by ready-by). No special "binary surplus" mode is added; the user who wants surplus absorption configures a current-type charger.

### D10 — Battery-absent case
When the system has no house battery (`capacity_kwh == 0`), the `soc_above_threshold` big-M gate that normally prioritises the battery collapses mathematically (`threshold_kwh = 0`, `M_soc = 0` → `0 ≥ 0`), so any configured surplus sinks fire freely — surplus routes to sinks immediately without waiting for a battery to fill. **The goal feature does not depend on having a house battery.**

## Risks / Trade-offs

- **[Risk] Hard target makes the solve infeasible.** → Mitigated by D2 making it soft (shortfall penalty); an unreachable target degrades to "charge as much as possible, report behind".
- **[Risk] Removing incentive buckets changes behaviour for users who tuned them.** → One-release deprecation: `penalty_levels` ignored with a warning + migrated to an equivalent target SoC. Documented in the migration plan.
- **[Risk] Surplus absorption silently does not happen for binary chargers, nor for current chargers not listed in `excess_pv.priority[]`.** → Accepted; documented explicitly (D9). A binary charger still receives the deadline-target scheduled charging (cheapest slot prices by ready-by); a current charger simply doesn't absorb surplus until the user adds an `ev` priority-list entry. Module 5 surfaces this gap in the dashboard with a hint.
- **[Trade-off] Decoupling the core from `price_forecast.enabled`.** → The feature now works for everyone immediately; only the multi-day spread depends on Module 1. This is a deliberate scope change from the original Module 4 (which gated everything on Module 1).

## Migration Plan

1. Add the new config fields + a default goal; accept `departure_time` as an alias and ignore `penalty_levels` with a deprecation warning (auto-migrate to a target SoC where possible). No behaviour change until the solver switch lands.
2. Switch Kepler from the incentive-bucket reward to the soft target-by-time requirement. Surplus routing is unchanged (already owned by `excess_pv.priority[]`). → Finding #1 resolved (a configured current-type charger listed in `excess_pv.priority[]` now charges from surplus PV and meets its target).
3. Wire `MultiDayPlanner` for far ready-by dates (forecast-gated, graceful fallback).
4. Expose `GET /api/ev/chargers`.
- **Rollback:** revert the Kepler switch (step 2) to restore incentive-bucket behaviour; config additions are additive and harmless.

## Resolved Questions
- **`EV_SHORTFALL_PENALTY` value:** 50.0 SEK/kWh. Defined as module constant `EV_SHORTFALL_PENALTY_DEFAULT = 50.0` in `kepler.py`; overridable via the advanced `kepler.ev_shortfall_penalty_sek_per_kwh` config key (wired through `KeplerConfig` + `adapter.py`, documented in `config.default.yaml`). The typical user never touches it.
- **Default `repeat` and `target_soc_percent`:** `daily` and 80%, respectively. Default `ready_by`: `"07:00"`.
- **`every_n_days` representation:** a separate `n_days: int` field on `EVChargerDeviceConfig` (used only when `repeat: every_n_days`), not an inline parameter in the enum string. KISS — keeps the enum a simple string and the cycle length a typed int field.

## References
- `openspec/changes/stabilization-review/findings.md` — Finding #1 + "Agreed Direction — EV charging (2026-06-06)".
- `price-forecasting-module-5` — UI (Energy Resources EV tab) + HA `input_datetime`/`input_number` sync.
