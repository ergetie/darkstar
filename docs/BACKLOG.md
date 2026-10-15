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

#### [Monitoring] Command Success Invariant Gives False Alarms

**Goal:** Stop reporting a healthy executor as failing, and show which action actually failed when something does.

**Notes:** Reported on Discord 2026-09-22 by two users, one with an EV: "tick success 57.51% over 24 h (82/193 failed)" while everything worked. `backend/monitors.py` computes the rate over throttled `execution_log` rows; failed ticks are always logged while healthy ones are throttled, so failures are over-weighted (the code comment admits the bias). Possible trigger, not confirmed: the EV charge-failure check marking ticks unsuccessful for a plugged-in or sleeping car. **(needs production data)**

#### [Settings] Water Heater Validation Error Traps The User

**Goal:** Let the user save and reach the Water tab to fix a mismatched control type, instead of being blocked by a save error.

**Notes:** Reported on Discord 2026-09-24: after turning "Smart water heater" off and on, saving is blocked by a "VVB switch is wrong" error, and the Water tab cannot be reached to fix it. Likely trigger, not confirmed: the save-blocking validation in `backend/api/routers/config.py` for a `switch.*` target with control type `temperature`. Needs a reproduction; the exact error was in a screenshot.

#### [Planner] Grid Charging Ignored By The Inverter AC Limit

**Goal:** Stop the planner from scheduling grid charging the inverter cannot deliver.

**Notes:** Found 2026-10-11 (battery benchmark investigation). For `dc_coupled`, `planner/solver/kepler.py:574-586` counts only PV-to-AC plus battery discharge against `max_inverter_ac_kw` (8 kW on the maintainer's prod); grid charging also passes through the inverter but is not counted. A hindsight re-solve on 2026-09-21/09-26 planned grid charging above 8 kW in a few slots. Adding the limit in the benchmark changed its result by <1 SEK over 22 days, so the live cost is likely small; not measured on live plans.

#### [Learning] Forecast created_at Never Updated On Overwrite

**Goal:** Know when each stored forecast was made, so forecast accuracy can be checked afterwards.

**Notes:** Found 2026-10-11. `slot_forecasts` rows are overwritten every run but `created_at` keeps the first insert time (`store.py:458-476`, unlike `store_plan` at line 567), so rows look ~7 days old. Earlier forecast versions (day-ahead, morning) are not kept anywhere, so day-ahead accuracy cannot be measured. Related: the Planner Run Archive item.

---

## 🔧 Improvements

#### [Settings] Warn About Out-Of-Range And Learning-Contradicted Settings

**Goal:** Tell the user when a setting is outside the range Darkstar's own learning would ever choose, or contradicts what the recorded data shows, and what it is likely costing them.

**Notes:** Found 2026-10-06 (cmon89): `forecasting.pv_confidence_percent` was 60 while Reflex only moves it within 70–120 (`backend/learning/reflex.py:22`) and his forecasts were 96 % accurate over 30 days (PV 938 actual vs 905 forecast). Nothing warned him. A replay estimated 60 % vs 83 % at ~53 kr over 25 days. His `learning.max_daily_param_change.pv_confidence_percent` was also 60 (default 1.0). Must cover every Reflex-tuned parameter (bounds table in `reflex.py`) and similar settings, e.g. max-daily-change values far from defaults. Harmless leftovers (e.g. an enabled `water_heaters` entry with `has_water_heater: false`, which the planner ignores) get at most a one-time info note, not a warning.

#### [Forecasting] Systematic PV Over-Forecast

**Goal:** Find and remove the cause of the PV forecast being consistently too high, instead of relying on `pv_confidence_percent` to hide it.

**Notes:** Found 2026-10-11 on the maintainer's prod (last-written aurora forecast vs recorded PV): bias +15 % Apr, +22 % May, +20 % Jun, +18 % Jul, +33 % Aug, +12 % Sep; also on clear days (median +14 %). Load is fine (−1 to −7 %). Raw Open-Meteo is +38–70 %, so Aurora already halves it; the prod setting `pv_confidence_percent: 83` removes most of the rest. Not clipping (max ~5.7 kW vs 8 kW inverter). Unchecked: whether a PV string/branch is missing from recorded `pv_kwh` (peak is only ~57 % of 10.08 kWp), array parameters, shading. **(needs production data)**

Update 2026-10-15 (Discord triage, Kristofer and youask report too-high forecasts causing grid buying): over 30 days (Sep 15 – Oct 14) the median day ratio actual/forecast is ~0.88 and 9 of 30 days missed by more than 30 % (mostly too high). An intraday correction from today's measured PV was tested and rejected for now: only 10–25 % less rest-of-day error, worse in ~25 % of cases and before 09:00. Fix the bias at the source instead. Unchecked: zero-export curtailment when the battery is full lowers recorded PV and may bias any actual-vs-forecast comparison. Only the latest forecast per slot is stored (`slot_forecasts` upsert); as-issued forecasts exist only in `planner_debug` (from 2026-10-06).

#### [Settings] Unused And Misleading Battery Power Settings

**Goal:** Remove or clearly label battery settings that do nothing, so users don't trust the wrong limit.

**Notes:** Found 2026-10-11 in prod `config.yaml` `battery:`: `max_charge_w`/`max_discharge_w: 5000` are only used when the inverter control unit is W (`executor/controller.py:145`, `:357`); in amp mode the real limit is `max_charge_a`/`max_discharge_a` (185 A × nominal voltage = 8.88 kW in the planner, `planner/solver/adapter.py:468`). A stray `max_charge_power_kw`/`max_discharge_power_kw: 8` under `battery:` is read only by `planner/strategy/manual_plan.py:40`. Check what the settings UI shows for each.

---

## ✨ New Features

#### [Debug] Planner Run Archive With UI Download

**Goal:** Keep every planning run's full inputs and plan (and planner/executor errors) for a set period, so past decisions can be replayed and shared for support; the user can download it from the Debug page and clear it.

**Notes:** Found 2026-10-06 (cmon89 investigation): past decisions could not be reconstructed. `schedule.json` already holds each run's full per-slot inputs (adjusted PV/load, prices) and plan, but is overwritten every run; `slot_plans`/`slot_forecasts` keep only the last value per slot; `debug.enable_planner_debug` stores only a 30-slot sample (`planner/output/debug.py`); the log rotates and is wiped on add-on restart. Verified that re-solving an archived `schedule.json` with the offline Kepler reproduces the real plan exactly (0/122 slots differ). Retention 60–90 days, gzip (~10 kB/run, ~0.5 MB/day). Include initial SoC, safety floor, config version, solver status. Storage location (DB vs files) to decide. Enables the automatic daily replay item. Temporary stand-in on the maintainer's prod since 2026-10-06: a root cron (every minute) gzips each new `schedule.json` into `/opt/darkstar/data/plan_archive/`, and `debug.enable_planner_debug: true` is set. Remove both when this item ships or the investigation (`ops/investigations/cmon-underperformance-2026-10-06.md`) no longer needs them.

#### [Planner] Power Tariff (Effekttariff) Awareness

**Goal:** Let the planner include a peak-power fee in its costs, so plans that avoid high grid peaks win on the real cost.

**Notes:** Requested on Discord 2026-09-23 by a user in Göteborg, who gets almost no grid cost running the battery on inverter auto. The maintainer stopped work on power tariffs earlier and said he would look again if several users have one. Starting point: `docs/designs/effekttariff-kiss.md` and `docs/designs/effekttariff-advanced.md` (designs only, nothing implemented). A "prefer self-consumption" mode and a way to disable idle were requested in the same conversation; that is a related but separate request. Needs a decision session first.

#### [Planner] Water Heater Tank Temperature Sensor

**Goal:** Let a user connect a temperature sensor on the water heater tank, so the planner can heat the water to a target temperature, and learn the usage pattern so it does not heat to maximum every time.

**Notes:** Suggested on Discord 2026-10-01. Open design questions: how the target temperature is chosen, how the usage pattern is learned, and how this fits with the existing water heater control. Not yet investigated.

#### [Planner] Per-Phase Load Awareness

**Goal:** Let the planner take expected per-phase house load and the main fuse into account, so it does not schedule EV charging (and other controlled loads) that the load balancer will have to throttle.

**Notes:** Today the planner only balances total energy (house load forecast plus an optional total `max_import_kw`); nothing in `planner/` knows about phases or `main_fuse_a`. On 2026-09-27 it planned 6.9 kW EV (10 A × 3) while the water heater and microwave sat on L3 (~10 A), forcing throttle to 6 A and then 1-phase relief on L1. Needs a per-phase load forecast (or per-device phase mapping) and a fuse constraint in Kepler. Controlling the water heater will reduce, but not remove, the clash.

#### [Load Balancer] Proportional Overload Timing

**Goal:** Make the load balancer's reaction time depend on how far a phase is over its limit, like a fuse's time-current curve: a small overshoot (e.g. 1–5% over) is tolerated for a while (e.g. ~30 s), while larger overshoots trigger throttling or 1-phase relief progressively faster. Short 10–20 s peaks slightly above the limit (microwave, kettle) should not cut EV charging immediately.

**Notes:** Raised 2026-09-27 during `ev-planned-phase-switching`. Applies to house-load overload handling, not planned phase-mode targets (those are stable per slot). First step: check how the balancer currently times overload reduction and relief, then define the curve and safe upper bounds relative to the main fuse rating.

#### [UI] User-Arranged Dashboard

**Goal:** Let users choose which cards the dashboard shows and where, so optional features (load balancer, EV, water) get their own card only for users who have them.

**Notes:** Raised 2026-10-05 during the Battery & Strategy card redesign. Idea: an edit mode on a grid where cards can be added, moved, resized and grouped into one cell as tabs (like `PowerFlowTabs`), with the layout saved per user. Likely needs a grid library such as `react-grid-layout` (new dependency, ask first). Main cost is not the grid but making every card work at any size, which also makes each later card change more expensive. A cheaper first step: a show/hide toggle for optional cards on the current fixed grid.

---

## 💡 Future Ideas / Deferred
