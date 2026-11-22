# Darkstar Energy Manager: Backlog

This document contains ideas, improvements, and tasks that are not yet scheduled for implementation.

---

## 🤖 AI Instructions (Read First)

1.  **Naming:** Use generic names (e.g., `Settings Cleanup`, `Chart Improvements`) until the item is promoted.

2.  **Sections:**
    - **📥 Inbox** — New bugs/requests added by the user, unsorted. AI sorts items into the sections below when processing them.
    - **🐛 Fixes** — Broken or incorrect behavior in existing functionality.
    - **🔧 Improvements** — Existing functionality made better, faster, more honest, or more maintainable (incl. tech debt, tooling, tests).
    - **✨ New Features** — Net-new capability, including UI additions.
    - **💡 Future Ideas / Deferred** — Brainstorming, or explicitly considered-and-deferred items with revisit triggers.

3.  **Workflow rules:**
    - When an item is processed into an OpenSpec change, DELETE it from this file immediately at change-creation time (the change tracks it from then on).
    - Investigations happen BEFORE a change is created — changes contain only atomic, clear, pre-decided implementation tasks, never "investigate X" tasks.
    - Items tagged **(needs production data)** cannot be implemented cold — they require a data-review session with the user first.
    - Change verification MUST visually check every page whose SHARED code was touched (e.g. `lib/api.ts`, chart helpers), not just the pages the change is "about" — other users run different configs than the maintainer.

4.  **Format:** Use the template below for new items.

### Backlog Item Template

```
#### [Category] Item Title

**Goal:** What we want to achieve.

**Notes:** Context, constraints, or design considerations.
```

---

## 📥 Inbox (User Added / Unsorted)

<!-- Add new bugs/requests here. AI sorts them into a section (or wipes them into an OpenSpec change) when processing. -->

---

## 🐛 Fixes

#### [Executor] Detect Inverter Mode Reverts And Power Mismatch

**Goal:** Warn when the inverter does not follow the commanded mode or power.

**Notes:** Status Reported, not verified; probably integration-side. Fronius GEN24: during grid charging `storage_control_mode` reverted from "Charge from Grid" to "Discharge Limit" 20 s to 17 min after each write, with no HA context; 3.3 kW commanded, ~0.4–0.6 kW delivered (01:00–02:00). The executor could detect commanded vs actual mismatch and warn. Source: GitHub #8 (Cm0n89), "Other findings".


---

## 🔧 Improvements

#### [Planner] Source-Dependent Max Battery Charge Power

**Goal:** Model that grid charging is capped by the inverter's AC limit while DC-coupled PV can charge faster.

**Notes:** Found 2026-11-22 (prod data). Grid-only charge peaks at 7.4–7.8 kW (8 kW AC limit minus ~7.5 % conversion loss); slots with PV reach 8.4 kW. The planner uses one battery charge limit (185 A ≈ 8.9 kW), so grid-charge plans overestimate by ~1 kW. Applies to DC-coupled hybrids (`system.inverter.topology: dc_coupled`, `max_ac_power_kw`).

#### [Learning] Replace Reflex With Measured, Stored Learned Parameters

**Goal:** Make Darkstar self-adapt where it actually helps: measure each home's physical facts (battery round-trip losses, real usable capacity, EV charging losses, real max charge/discharge power) from data, store them outside `config.yaml` with evidence, confidence and history, and use them unless the user locks their own value. Notify on every change; never auto-tune user preferences (risk, min SoC). Prove benefit with the hindsight benchmark.

**Notes:** Status Investigated 2026-11-19/20 (code + prod data). Design via openspec-explore before any change; not scheduled yet. Facts:
- Reflex (`backend/learning/reflex.py`) has not run automatically since the FastAPI migration (`06b40f9a`); it edits `config.yaml` directly.
- Backtest on a prod DB copy, 368 days (2025-11-17 to 2026-11-19), day-by-day dry run (`~/.cache/darkstar-reflex-backtest/`): 18 changes. `base_factor` 1.10 → 1.00 in 10 days (prod had 0 low-SoC events in 16–20h; missing history counted as "no events"). `pv_confidence` 83 → 70 in 3 days (June), stuck at the bound 115 days, then 70 → 95 in 5 days (Nov 15–19). Capacity 0 changes. EV losses 0 changes (14 starts, needs 20).
- `pv_confidence` tuning cannot converge: Reflex measures the stored forecast, but the factor is applied later in the planner (`planner/inputs/data_prep.py:206`), so its own changes never reach what it measures.
- `pv_confidence` cuts an already ML-corrected forecast: Aurora's `pv_forecast_kwh` = Open-Meteo baseline + bounded, weighted ML residual (`ml/forward.py:176`, `:739`); prod runs hybrid mode at 100 % weight (91/14 paired days). Prod 2026-11-01 to 11-19 (1824 slots, latest stored forecast per slot, not day-ahead): Open-Meteo 169.7 kWh, Aurora 104.2 kWh, planner after 83 % = 86.5 kWh, actual 117.0 kWh.
- `base_factor` is only the fallback when the default `probabilistic` S-index (`config.default.yaml:204`) fails; the margin already adapts from forecast p10/p90.
- Capacity estimator (`store.py:1031` `get_capacity_estimate`) is broken, not the data: it requires `soc_start_percent`, which the recorder never writes (`backend/recorder.py:611` writes only `soc_end_percent`; prod 2026-11-21: start filled in 11 of 36,846 `slot_observations` rows, end filled in 36,692). The previous slot's `soc_end_percent` works as the start, which is how `backend/battery_benchmark.py:238-243` fits capacity. 1 % SoC steps make single-slot estimates noisy, so estimate over multi-slot segments. The existing hindsight capacity warning covers degradation.
- Lesson from #8: a learned value must expire and say so when stale (the old `learning_daily_metrics` row overrode `base_factor` with 1.4066 from 2026-03-15 to 2026-11-19).
- Related: memory note on treating `pv_confidence` as a safety margin only (PV forecast fix list, 2026-11-04).
- Backtests 2026-11-22 (prod, read-only; scripts in `~/.cache/darkstar-*-backtest/`): battery DC counters (`sensor.inverter_battery_power`) are battery-side, so measured round-trip ~0.96 excludes inverter loss. Inverter loss fits as ~60 W standby + ~7.5 % of charge energy (beats a fixed % by ~2x in walk-forward); discharge/PV conversion loss can't be separated with current sensors. `sensor.inverter_power_losses` equals the balance residual (usable target, not independent). Kepler (`planner/solver/kepler.py:783`) has no separate inverter loss. Capacity: only as a change warning (one module offline 2026-08-24..09-18 read 18–20 kWh; winter reads +20 %). Max power: warn only (grid ~7.4–7.8 kW is the AC limit, normal). EV loss from car meter 5–6.5 % matches config. 85 % of discharge shortfall is house using less than planned.
- Proposed shape: learn battery RTE, inverter standby and charge loss (add an inverter-loss term to the planner); warn on capacity/max-power changes; learn EV loss from the car meter after ~10 sessions. Depends on the water-clamp fix; car meter (`sensor.tesla_ble_energy_added`) configured on prod 2026-11-22.
Source: GitHub #8 review and Reflex backtest.

#### [Settings] Warn About Out-Of-Range And Learning-Contradicted Settings

**Goal:** Tell the user when a setting is outside the range Darkstar's own learning would ever choose, or contradicts what the recorded data shows, and what it is likely costing them.

**Notes:** Found 2026-10-06 (cmon89): `forecasting.pv_confidence_percent` was 60 while Reflex only moves it within 70–120 (`backend/learning/reflex.py:22`) and his forecasts were 96 % accurate over 30 days (PV 938 actual vs 905 forecast). Nothing warned him. A replay estimated 60 % vs 83 % at ~53 kr over 25 days. His `learning.max_daily_param_change.pv_confidence_percent` was also 60 (default 1.0). Must cover every Reflex-tuned parameter (bounds table in `reflex.py`) and similar settings, e.g. max-daily-change values far from defaults. Harmless leftovers (e.g. an enabled `water_heaters` entry with `has_water_heater: false`, which the planner ignores) get at most a one-time info note, not a warning.

---

## ✨ New Features

#### [Planner] Planned 1-Phase Mode For Phase-Switching Chargers

**Goal:** Let the planner choose 1-phase charging for phase-switching EV chargers when that suits the plan, instead of always planning the 3-phase floor.

**Notes:** Low priority: at runtime 1-phase only happens during PV surplus charging or load-balancer relief. Today Kepler has no 1-phase mode (planned power never goes below the 3-phase floor, `backend/core/ev_power.py`), so `ev-single-phase-grid-limit` treats these chargers as 3-phase. Option A: a binary `ev_1p` plus split energy `ev_energy_1p`/`ev_energy_3p` to keep the model linear, and apply the per-line phase row to `ev_energy_1p` on `phase_1_line`. Changes plans and the EV loss model. Size M.

#### [Planner] Power Tariff (Effekttariff) Awareness

**Goal:** Let the planner include a peak-power fee in its costs, so plans that avoid high grid peaks win on the real cost.

**Notes:** Requested on Discord 2026-09-23 by a user in Göteborg, who gets almost no grid cost running the battery on inverter auto. The maintainer stopped work on power tariffs earlier and said he would look again if several users have one. Starting point: `docs/designs/effekttariff-kiss.md` and `docs/designs/effekttariff-advanced.md` (designs only, nothing implemented). A "prefer self-consumption" mode and a way to disable idle were requested in the same conversation; that is a related but separate request. Needs a decision session first.

#### [Planner] Water Heater Tank Temperature Sensor

**Goal:** Let a user connect a temperature sensor on the water heater tank, so the planner can heat the water to a target temperature, and learn the usage pattern so it does not heat to maximum every time.

**Notes:** Suggested on Discord 2026-10-01. Open design questions: how the target temperature is chosen, how the usage pattern is learned, and how this fits with the existing water heater control. Not yet investigated.

#### [Planner] Per-Phase Load Awareness

**Goal:** Let the planner take expected per-phase house load and the main fuse into account, so it does not schedule EV charging (and other controlled loads) that the load balancer will have to throttle.

**Notes:** `ev-single-phase-grid-limit` added a per-phase limit (main fuse × load-balancing margin) for fixed 1-/2-phase EV chargers, assuming non-EV load spreads evenly over 3 phases. On 2026-09-27 the planner had planned 6.9 kW EV (10 A × 3) while the water heater and microwave sat on L3 (~10 A), forcing throttle to 6 A and then 1-phase relief on L1. Done 2026-11: per-device `water_heaters[].phases`, counted by the planner's per-phase limit and shared with the load balancer (`water-heater-phase-aware-planning`). Still missing: a per-phase house-load forecast (only worth building if real cases show up) and per-phase handling of other single-phase non-EV loads.

#### [UI] User-Arranged Dashboard

**Goal:** Let users choose which cards the dashboard shows and where, so optional features (load balancer, EV, water) get their own card only for users who have them.

**Notes:** Raised 2026-10-05 during the Battery & Strategy card redesign. Idea: an edit mode on a grid where cards can be added, moved, resized and grouped into one cell as tabs (like `PowerFlowTabs`), with the layout saved per user. Likely needs a grid library such as `react-grid-layout` (new dependency, ask first). Main cost is not the grid but making every card work at any size, which also makes each later card change more expensive. A cheaper first step: a show/hide toggle for optional cards on the current fixed grid.

---

## 💡 Future Ideas / Deferred
