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

#### [Config] Dead Round-Trip Efficiency Setting And Implicit Discharge Efficiency

**Goal:** Make the battery efficiency settings honest: remove the setting that does nothing and state the discharge efficiency the planner actually uses.

**Notes:** Verified 2026-10-04. `battery.roundtrip_efficiency_percent` (`config.default.yaml:54`, 95.0) is read by no application code; its comment says "used only in planner/simulation.py", which no longer exists. Remaining references: `samples/config.sample.json`, `scripts/test_edge_cases.py`, `scripts/test_bulk_mode.py`. Separately, `config.default.yaml` sets `charge_efficiency: 0.92` but has no `discharge_efficiency`, so the solver uses the code default of 0.95 (`planner/solver/adapter.py:494`) and plans with ~87.4% round trip, not the 95% the dead setting suggests. Fix: remove the dead key (and decide whether the config migration strips it from existing `config.yaml` files), and add `discharge_efficiency: 0.95` explicitly to `config.default.yaml`.

#### [UI] Battery & Strategy Card Ignores The Price Reserve

**Goal:** Show the real end-of-plan battery target on the Battery & Strategy card, including the price reserve, and explain why it is held.

**Notes:** Found 2026-10-05 after the `d2-price-reserve` change. `frontend/src/components/BatteryStrategyCard.tsx:288` shows `safety_floor.calculated_floor_kwh` (deficit floor only), and "Tradable" (line 311) is derived from it, so both are wrong whenever the price reserve raises the target (`safety_floor.final_floor_kwh`). The "deficit" figure shows `base_reserve_kwh` before the risk cap, so "min 4.0 · deficit 20.1" can read as 24 kWh while the floor is 9.4 kWh. Fix: show `final_floor_kwh`, add a price reserve line using `price_reserve_applied_kwh` and `price_reserve_reason` (plain words, e.g. "Holding 16 kWh: Tuesday's cheapest charging ~1.40 vs 0.80 now"), show the capped deficit value, and follow `docs/design-system/AI_GUIDELINES.md`.

---

## 🔧 Improvements

#### [Monitoring] Plan Freshness Error Message Is Not User-Friendly

**Goal:** Make the plan freshness error say in plain words that no new plan has been produced, and what the user should check, instead of pointing at developer-only artifacts.

**Notes:** Found 2026-10-04. The current guidance ("See /api/system/monitors for evidence; check findings ledger") refers to an internal review file. Also note `first_detected_at` only reflects the first check since the last backend restart, not when the outage began, so the message can mislead about timing.

---

## ✨ New Features

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

---

## 💡 Future Ideas / Deferred

#### [EV] 1-Phase Fallback Under-Delivery

**Goal:** Evaluate whether the planner should account for runtime 1-phase degradation when planning EV goal charging.

**Notes:** The planner plans at the configured phase count. When the load balancer drops a charger to 1-phase to relieve a phase overload (`load-balancer-graceful-degradation`), actual delivery falls below plan until the next re-plan. Accepted as a known limitation on 2026-09-25. Revisit trigger: production data shows goals missed or at risk because of frequent 1-phase relief.
