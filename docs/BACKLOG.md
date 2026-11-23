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
