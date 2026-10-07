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

---

## 🔧 Improvements

#### [Settings] Warn About Out-Of-Range And Learning-Contradicted Settings

**Goal:** Tell the user when a setting is outside the range Darkstar's own learning would ever choose, or contradicts what the recorded data shows, and what it is likely costing them.

**Notes:** Found 2026-10-06 (cmon89): `forecasting.pv_confidence_percent` was 60 while Reflex only moves it within 70–120 (`backend/learning/reflex.py:22`) and his forecasts were 96 % accurate over 30 days (PV 938 actual vs 905 forecast). Nothing warned him. A replay estimated 60 % vs 83 % at ~53 kr over 25 days. His `learning.max_daily_param_change.pv_confidence_percent` was also 60 (default 1.0). Must cover every Reflex-tuned parameter (bounds table in `reflex.py`) and similar settings, e.g. max-daily-change values far from defaults. Harmless leftovers (e.g. an enabled `water_heaters` entry with `has_water_heater: false`, which the planner ignores) get at most a one-time info note, not a warning.

---

## ✨ New Features

#### [Debug] Planner Run Archive With UI Download

**Goal:** Keep every planning run's full inputs and plan (and planner/executor errors) for a set period, so past decisions can be replayed and shared for support; the user can download it from the Debug page and clear it.

**Notes:** Found 2026-10-06 (cmon89 investigation): past decisions could not be reconstructed. `schedule.json` already holds each run's full per-slot inputs (adjusted PV/load, prices) and plan, but is overwritten every run; `slot_plans`/`slot_forecasts` keep only the last value per slot; `debug.enable_planner_debug` stores only a 30-slot sample (`planner/output/debug.py`); the log rotates and is wiped on add-on restart. Verified that re-solving an archived `schedule.json` with the offline Kepler reproduces the real plan exactly (0/122 slots differ). Retention 60–90 days, gzip (~10 kB/run, ~0.5 MB/day). Include initial SoC, safety floor, config version, solver status. Storage location (DB vs files) to decide. Enables the automatic daily replay item.

#### [Learning] Automatic Daily Replay ("Missing Profit" Self-Check)

**Goal:** Every night, replay yesterday with the real PV, load and prices and compare three results: what Darkstar actually did, what its own planner would have done with perfect information (and with the user's settings), and plain self-use. Report the gaps in plain words, e.g. "you missed ~X kr; likely cause: execution / forecasts / setting Y".

**Notes:** Proven offline in the 2026-10-06 cmon89 investigation (`ops/investigations/cmon-2026-10/`, `kepler_replay2.py`): real Kepler re-planned every 30 min on actual data, executed through a per-install calibrated loss model; replay reproduced the maintainer's real result within ~5 kr. Solves take ~0.1 s, so a day is ~10 s of CPU. Gap real-vs-replay points to execution problems; replay-vs-perfect points to forecasts or settings; replay with alternative settings quantifies "what if". Depends on persisting planner runs/inputs (separate item) and on the fair baseline item for the self-use side.

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

#### [EV] 1-Phase Fallback Under-Delivery

**Goal:** Evaluate whether the planner should account for runtime 1-phase degradation when planning EV goal charging.

**Notes:** The planner plans at the configured phase count. When the load balancer drops a charger to 1-phase to relieve a phase overload (`load-balancer-graceful-degradation`), actual delivery falls below plan until the next re-plan. Accepted as a known limitation on 2026-09-25. Revisit trigger: production data shows goals missed or at risk because of frequent 1-phase relief.
