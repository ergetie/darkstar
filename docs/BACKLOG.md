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

#### [EV] Shared Live EV State Reader

**Goal:** One helper that reads a charger's live SoC and plug state, used by both the manual-charge start API and the executor's per-tick end detection.

**Notes:** Today `backend/api/routers/ev.py` (`start_ev_manual_charge`, via `get_ha_sensor_float` / `get_ha_entity_state` / `resolve_plug_state`) and `executor/engine.py` (`_check_ev_manual_charge_end`, via `ha_client.get_state_value` / `is_unreachable_state` / `is_ev_plugged_in`) read the same sensors separately, with slightly different handling of unavailable/non-numeric values. Works now, but the two can drift. Found during ev-manual-charge-and-node verification.

#### [EV] Manual Charge Status Source in Charger API

**Goal:** Decide on one source of truth for `manual_charge` in `GET /api/ev/chargers`.

**Notes:** The endpoint reads `manual_charge` from `data/ev_multi_day_state.json` (`ev.py`, charger list builder), not from the executor's in-memory `_ev_manual_charge`. They agree today because `set_/clear_ev_manual_charge` always update both together. If either is ever written alone, the UI could show a stale or missing manual charge. Options: read from `executor.get_ev_manual_charge_status()` when the executor is available, or add a consistency test. Found during ev-manual-charge-and-node verification.

---

## ✨ New Features

<!-- Empty -->

---

## 💡 Future Ideas / Deferred

<!-- Empty -->
