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

<!-- Empty. Previously held the flaky `test_executor_ev_switch_not_opened_without_schedule` item (observed 2026-07-06, ~1-in-5-8 full-suite failure rate) — declared unreproducible 2026-07-13 after 35/35 clean full-suite runs (code review eliminated in-test causes; no DB-lock errors observed). Evidently fixed incidentally by EV/executor changes landed since. Reopen only if it fails again in CI. -->

---

## 🔧 Improvements

<!-- The three price-forecast/S-Index "(needs production data)" calibration items were resolved by the 2026-07-17 replay investigation (97 days of prod forecasts + last winter's actuals): RISK_PRICE_KW_FRACTION keeps its values and pure-peak stays (verdicts + evidence recorded in openspec/changes/price-alert-accuracy/proposal.md); the alert-accuracy work was promoted into the price-alert-accuracy change. -->


## ✨ New Features

#### [UI] Settings Search / Command Palette (Ctrl+K)

**Goal:** Implement a global quick search bar or keyboard command palette at the top of the settings page.

**Notes:** Allows users to jump directly to any configuration field (e.g. "Main Fuse") across the System, EV, Water, Load Balancing, UI, and Advanced tabs without manual navigation.

---

#### [UI] Live Load-Balancer Status Overlay on Dashboard

**Goal:** Display a live phase current (L1, L2, L3) bar graph and overload status overlay on the main dashboard.

**Notes:** Highlights active load shedding, EV charger throttling, or stale-sensor fallback alerts, including a one-click manual bypass/override control.

---

## 💡 Future Ideas / Deferred

<!-- The `max_safety_buffer_pct` risk-differentiation item was promoted into the risk-aware-safety-buffer-cap change (2026-07-18). The planner-awareness-of-sustained-phase-overload item was scrapped 2026-07-18 (edge case, mitigated by SoC re-read + early replan). -->

#### [UI] Expand Settings-Search User Guides

**Goal:** Grow the in-app guide library beyond the initial 4–5 guides shipped with the settings search.

**Notes:** The settings search (see the settings-search change, discussed 2026-07-18) launches with short guides for Load Balancing, EV Charging, Water Heater, Battery/S-Index, and Solar Forecast. Later, add guides for the remaining functions (e.g. price alerts, vacation mode, excess-PV priority, advisor/LLM, quick actions) and consider deepening existing ones. Revisit trigger: after the settings-search change ships and has been used for a while.
