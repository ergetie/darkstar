## Context

Stabilization-review **Finding #1 (S1)** confirmed that EV charging exports surplus PV instead of charging because the only thing that values EV charging in the Kepler objective is the configured incentive-bucket reward (`ev_bucket_charged · value_sek`), which:
- is **zero by default** (`penalty_levels: []`) → the EV never charges, surplus is exported;
- only wins against export when the user-set `value_sek` exceeds the spot export price, and only wins against grid when it exceeds the import price — i.e. it is a hand-tuned reservation price;
- can never *guarantee* a charge level by a time — it is a willingness-to-pay, not a requirement.

The home battery does not work this way: it simply charges from the cheapest energy (and free PV) toward its targets. This change makes the EV behave the same, driven by a user **goal** instead of a price knob.

Key existing code:
- `planner/pipeline.py`: per-charger EV deadline calculation (~line 536–593).
- `planner/solver/kepler.py`: incentive-bucket setup (`:203–234`), per-slot objective (`:489–500`), bucket reward (`:642–651`), per-device `ev_energy[d][t]` variables and deadline constraints.
- `planner/solver/adapter.py`: builds `EVChargerInput`; maps `penalty_levels` → `IncentiveBucket` (`:146–154`).
- `executor/config.py`: `EVChargerDeviceConfig` (`departure_time`, `switch_entity`, `penalty_levels`, …).

## Goals / Non-Goals

**Goals:**
- Replace the penalty-level EV economics with a goal-based model (`target_soc_percent` by `ready_by`, optionally repeating).
- Make a configured charger charge correctly out of the box (sensible default goal; no price knowledge required).
- Always self-consume excess PV (battery/EV per a simple priority switch) before exporting.
- Spread charging across cheaper days automatically when the ready-by date is far and a forecast exists.
- Keep the engine usable by the executor's switch control (`keep_on_after_target`) and by Module 5's UI/HA layer.

**Non-Goals:**
- No UI or HA entity sync here (Module 5).
- No V2G / EV-to-house discharge.
- No per-band willingness-to-pay (penalty levels are retired, not re-skinned).
- The `MultiDayPlanner` stays load-agnostic (no EV-specific logic inside it).

## Decisions

### D1 — Goal model: target SoC + ready-by time + optional repeat (one concept)
Per charger the user sets `target_soc_percent`, a `ready_by` time (`HH:MM`), and a `repeat` rule. `repeat ∈ {daily, weekdays, weekends, every_n_days(n), none}`. With `repeat: none` the user also sets a `ready_by_date` (a one-off specific date). **A specific date is just "no repeat" — there is no separate "daily vs multi-day" mode** (the prior Module 4/5 mode dropdown is removed). The pipeline resolves the *next* ready-by datetime from these fields each run.

### D2 — Requirement replaces incentive: soft "reach target by deadline" constraint
The incentive-bucket variables and the `Σ ev_bucket_charged · value_sek` reward are **removed** from Kepler. In their place, for each plugged charger with a goal:
```
delivered_kwh + shortfall[d]  >=  required_kwh        # soft
objective += shortfall[d] * EV_SHORTFALL_PENALTY      # large, internal, fixed
```
where `delivered_kwh = Σ ev_energy[d][t]` over slots up to the deadline. **Soft on purpose:** if the car physically cannot reach the target in time (short window / low power), the solve stays feasible and `shortfall` simply surfaces as "behind". `EV_SHORTFALL_PENALTY` is a fixed internal constant set well above any plausible import price, so the solver treats the target as near-mandatory but never charges from absurdly-priced grid beyond what the requirement needs. **The user never sets a SEK value.**

### D3 — `required_kwh` derived from target SoC, not typed by the user
`required_kwh = max(0, (target_soc_percent − current_soc_percent)/100 · battery_capacity_kwh) − energy_already_delivered_this_cycle`. Current SoC and battery capacity come from existing charger state/config; delivered energy from `slot_observations`. The user expresses intent in %, the system works in kWh internally.

### D4 — Excess PV is always self-consumed before export; priority switch breaks the tie
Add a small self-consumption preference to the objective so that, when surplus PV exists, it is routed to the battery and/or EV before being exported (export revenue is near-zero exactly when PV is high, so this is almost always free). A per-charger `charge_priority ∈ {battery, ev}` (default `battery`) decides who gets the *free* surplus first. This is a **tie-break only**: the hard arbitrage/requirement economics still dominate, so the switch never forces expensive grid or starves a deadline.

### D5 — `keep_on_after_target`
A per-charger boolean (default false). When the target is met, the planner keeps the charger's intended switch state ON through the ready-by time (the car draws ~0 but its heater/pre-conditioning can run). Pure flag on the plan; the executor's existing switch control (and Module 5) honour it.

### D6 — `MultiDayPlanner` survives, invoked automatically, decoupled from Module 1
The reusable, load-agnostic `MultiDayPlanner` (inverse-price daily-quota allocation, min-daily-fraction floor, power-cap redistribution, graceful no-forecast fallback) is kept. It is invoked **automatically** when the resolved deadline is more than one day out **and** a 7-day forecast is available; it returns today's `daily_quota_kwh`, which becomes an upper bound on today's EV energy in Kepler. **The core goal feature needs only the day-ahead Nordpool prices the planner already has and is NOT gated behind `price_forecast.enabled`.** Without a forecast, no quota is applied and Kepler charges as cheaply as it can within the known horizon, filling the rest as the deadline nears (the min-daily-fraction logic only applies when spreading).

### D7 — Config schema + deprecation
New per-charger fields: `target_soc_percent` (int), `ready_by` (`HH:MM`), `repeat` (enum, default `daily`), `ready_by_date` (date, when `repeat: none`), `keep_on_after_target` (bool, default false), `charge_priority` (`battery`|`ev`, default `battery`). **`penalty_levels` is retired**; if present it is ignored with a one-release deprecation warning and, where possible, migrated to an equivalent goal (target = highest configured `max_soc`). `departure_time` is accepted as a deprecated alias for `ready_by`. A sensible default goal ships so a configured charger charges out of the box.

### D8 — Read-only state API
`GET /api/ev/chargers` returns per charger: live `plugged_in` / `soc_percent` / `power_kw` (from HA, fetched on request), the goal (`target_soc_percent`, `ready_by`, `repeat`, resolved next `deadline`), `required_kwh` / `delivered_kwh` / `remaining_kwh`, today's `daily_quota_kwh` (null when not spreading), an optional `quota_schedule` (when multi-day), and a `status ∈ {on_track, behind, complete, idle}`. Transient state is written to `data/ev_multi_day_state.json` each run; the endpoint merges it with live sensors. No DB table.

## Risks / Trade-offs

- **[Risk] Hard target makes the solve infeasible.** → Mitigated by D2 making it soft (shortfall penalty); an unreachable target degrades to "charge as much as possible, report behind".
- **[Risk] Removing incentive buckets changes behaviour for users who tuned them.** → One-release deprecation: `penalty_levels` ignored with a warning + migrated to an equivalent target SoC. Documented in the migration plan.
- **[Risk] Self-consumption preference distorts battery arbitrage.** → It is a small tie-break weight applied only to *surplus* routing, dominated by real import/export economics; verified against the operator's config that battery arbitrage is unchanged when no EV surplus is in play.
- **[Risk] `charge_priority: ev` could starve the home battery before an evening peak.** → Accepted and user-chosen; the requirement/arbitrage still routes PV to whichever genuinely needs it for a deadline, so the switch only governs otherwise-equal free surplus.
- **[Trade-off] Decoupling the core from `price_forecast.enabled`.** → The feature now works for everyone immediately; only the multi-day spread depends on Module 1. This is a deliberate scope change from the original Module 4 (which gated everything on Module 1).

## Migration Plan

1. Add the new config fields + a default goal; accept `departure_time` as an alias and ignore `penalty_levels` with a deprecation warning (auto-migrate to a target SoC where possible). No behaviour change until the solver switch lands.
2. Switch Kepler from the incentive-bucket reward to the soft target-by-time requirement + self-consumption priority. → Finding #1 resolved (a configured charger now charges from surplus PV and meets its target).
3. Wire `MultiDayPlanner` for far ready-by dates (forecast-gated, graceful fallback).
4. Expose `GET /api/ev/chargers`.
- **Rollback:** revert the Kepler switch (step 2) to restore incentive-bucket behaviour; config additions are additive and harmless.

## Open Questions
- Exact value of `EV_SHORTFALL_PENALTY` and the self-consumption tie-break weight (internal constants; default in tasks, tunable in config if needed).
- Default `repeat` and default `target_soc_percent` for a freshly configured charger (proposed: `daily`, 80%).

## References
- `openspec/changes/stabilization-review/findings.md` — Finding #1 + "Agreed Direction — EV charging (2026-06-06)".
- `price-forecasting-module-5` — UI (Energy Resources EV tab) + HA `input_datetime`/`input_number` sync.
