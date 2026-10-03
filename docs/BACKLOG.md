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

---

## 🔧 Improvements

<!-- Empty -->

---

## ✨ New Features

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
