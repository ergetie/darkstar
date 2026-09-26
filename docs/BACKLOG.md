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

#### [Tests] Time-Dependent Load Profile Test

**Goal:** Make `tests/backend/test_ha_client_load_profile.py::TestDeltaGuard::test_custom_max_meter_delta_kwh_is_honored` deterministic.

**Notes:** The test builds its fixture history from `datetime.now()` (line ~23), so the injected 30 kWh jump can fall outside the profile window depending on the time of day. It passed all day 2026-09-25 and failed on 2026-09-26 on a clean HEAD. Pin the clock (freeze time or pass an explicit `now`) instead of loosening the assertion.

---

## ✨ New Features

<!-- Empty -->

---

## 💡 Future Ideas / Deferred

#### [EV] 1-Phase Fallback Under-Delivery

**Goal:** Evaluate whether the planner should account for runtime 1-phase degradation when planning EV goal charging.

**Notes:** The planner plans at the configured phase count. When the load balancer drops a charger to 1-phase to relieve a phase overload (`load-balancer-graceful-degradation`), actual delivery falls below plan until the next re-plan. Accepted as a known limitation on 2026-09-25. Revisit trigger: production data shows goals missed or at risk because of frequent 1-phase relief.
