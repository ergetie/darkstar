# Darkstar Energy Manager: Backlog

This document contains ideas, improvements, and tasks that are not yet scheduled for implementation. Items here are moved to [PLAN.md](PLAN.md) when they become active priorities.

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is organized by category. Items do **not** have strict ordering.

2.  **Naming:** Use generic names (e.g., `Settings Cleanup`, `Chart Improvements`) until the item is promoted.

3.  **Promotion Flow:** 
    - When starting work on a backlog item, assign it a proper **Rev ID** following the [naming conventions in PLAN.md](PLAN.md#revision-naming-conventions).
    - Move the item to `PLAN.md` with status `[PLANNED]` or `[IN PROGRESS]`.
    - Delete the item from this file.

4.  **Categories:**
    - **Backlog** — Concrete tasks ready for implementation
    - **On Hold** — Paused work with existing code/design
    - **Future Ideas** — Brainstorming, needs design before implementation

5.  **Format:** Use the template below for new items.

### Backlog Item Template

```
### [Category] Item Title

**Goal:** What we want to achieve.

**Notes:** Context, constraints, or design considerations.
```

---

## 📋 Backlog

### [Settings] Settings Page Audit & Cleanup

**Goal:** Ensure the Settings page is the complete source of truth for all configuration.

**Tasks:**
- Audit discrepancies between Settings UI and `config.yaml`/`secrets.yaml`
- Implement "Normal" vs "Advanced" settings mode toggle
- Add inline help/tooltips for every setting
- Identify and remove any unused config keys
- Add comments to `config.default.yaml` explaining each option

**Notes:** User should never need to manually edit `config.yaml` after initial setup.

---

### [Docs] First-Time Setup Guide

**Goal:** Create a comprehensive setup guide in `README.md` for new users.

**Scope:**
- Post-installation steps (after Docker/HA Add-on is running)
- Configure HA connection
- Set up sensors
- Configure battery/solar/water heater parameters
- Verify system is working

**Notes:** Should cover both standalone Docker and HA Add-on paths.

---

### [UI] Entity Selector Improvements

**Goal:** Fix the entity selector dropdowns in Settings to be searchable and visually consistent.

**Problems:**
- Current dropdowns show full list without search (unusable with 100+ entities)
- Visual style is "Win95" - doesn't match the modern theme
- No filtering or fuzzy search

**Solution:** Implement searchable combobox component (react-select or similar).

---

### [UI] Dashboard Chart History Missing

**Goal:** Investigate and fix why historical data is not showing in the main Dashboard chart.

**Symptoms:**
- Chart only shows planned/future data
- No "actual" SoC/PV/Load history displayed
- Might be related to Executor being inactive

**Notes:** Need to verify data flow from HA → SQLite → Chart.

---

### [UI] Chart Improvements (Polish)

**Goal:** Enhance all charts with better UX and visual polish.

**Tasks:**
- Render `soc_target` as a step-line series (not smooth)
- Add zoom support (mouse wheel + controls)
- Offset tooltips to avoid covering data points
- Ensure price series includes full 24h even if schedule is partial
- Mobile responsiveness improvements

**Notes:** Needs design brainstorm before implementation.

---

### [UI] UX/UI Review

**Goal:** Comprehensive review of all tabs for usability improvements.

**Scope:**
- Review each tab for clarity and flow
- Identify confusing UI elements
- Add info/explanation buttons or hover tooltips where needed
- Mobile responsiveness audit

---

### [Planner] Proactive PV Dump (Water Heating)

**Goal:** Schedule water heating to `temp_max` proactively when PV surplus is forecasted.

**Current State:** PV dump is only handled reactively via `excess_pv_heating` override in executor.

**Proposed Change:** Kepler solver should anticipate forecasted PV surplus at SoC=100% and pre-schedule water heating.

---

### [Backend] Migrate Away from Eventlet

**Goal:** Replace deprecated Eventlet with a modern async solution.

**Current State:**
```
DeprecationWarning: Eventlet is deprecated. It is currently being maintained 
in bugfix mode, and we strongly recommend against using it for new projects.
```

**Options:**
- Migrate to native `asyncio` + `aiohttp`
- Use `gevent` (similar API but maintained)
- Use Flask-SocketIO with native threading

**Impact:** Affects WebSocket implementation and background threads.

**Notes:** See https://eventlet.readthedocs.io/en/latest/asyncio/migration.html

---

### [UI] Light/Dark Theme Switcher

**Goal:** Add a light/dark mode toggle to the sidebar for quick theme switching.

**Current State:**
- Theme infrastructure exists in `Settings.tsx`
- Multiple themes available via API
- No quick-toggle in sidebar

**Tasks:**
- Categorize existing themes as "light" or "dark"
- Add sun/moon toggle icon to sidebar
- Store user preference (localStorage + config)
- Default to system preference if not set

---

### [Ops] Database Consolidation

**Goal:** Merge SQLite databases from multiple environments into one unified dataset.

**Context:**
- Local dev machine has data
- CT107 (active server) has execution history
- CT114 (bleeding edge) has data too
- Need one clean database with no gaps

**Notes:** One-time ops task. Backup everything first!

---

### [Ops] MariaDB Sunset

**Goal:** Remove MariaDB dependency and make SQLite the only database.

**Current State:** System works with SQLite only. MariaDB is optional but adds complexity.

**Tasks:**
- Audit which features still use MariaDB
- Migrate any required data/features to SQLite
- Remove MariaDB connection code
- Update documentation

**Notes:** Needs investigation before implementation.

---

### [HA] Entity Config Consolidation

**Goal:** Evaluate whether HA entity toggles (vacation mode, learning, etc.) should be in config.yaml or HA.

**Current State:** Some features read HA entity state at runtime, some use config.yaml.

**Questions:**
- Should toggles live in both places?
- Should HA override config.yaml?
- How to keep them in sync?

**Notes:** Needs design discussion. HA entities are useful for automations.

---

## ⏸️ On Hold

### Rev 63 — Export What-If Simulator

**Goal:** Deterministic way to answer "what if we export X kWh at tomorrow's price peak?" - show net SEK impact.

**Status:** On Hold (prototype exists but parked for Kepler pivot).

**Notes:** The current "Lab" tab was meant for this but needs complete redesign.

---

## 🔜 Future Ideas

### [Planner] Effekttariffer (Power Tariffs)

**Goal:** Support Swedish "effekttariff" (peak demand charges) in the planner.

**Concept:** Penalty for high grid import during certain hours. Planner needs to know about this to optimize import timing.

**Notes:** Needs design brainstorm. Would affect Kepler solver constraints.

---

### [Planner] Smart EV Integration

**Goal:** Prioritize home battery vs EV charging based on departure time.

**Inputs Needed:**
- EV departure time (user input or calendar integration)
- EV target SoC
- EV charger entity

**Notes:** Big feature. Requires careful UX design.

---

### [Lab] What-If Simulator Redesign

**Goal:** Redesign the Lab tab as a proper what-if simulator.

**Features:**
- Change battery size, PV array size, etc.
- See impact on daily/monthly costs
- Compare current vs hypothetical systems

**Notes:** Lab tab is currently hidden. Needs complete redesign before reactivation.

---

### [UI] Contextual Help System

**Goal:** Add info buttons and hover tooltips throughout the UI.

**Features:**
- Small (i) icons next to complex settings
- Hover for quick explanation
- Click for detailed help modal

---

### [Aurora] Multi-Model Forecasting

**Goal:** Separate ML models for different contexts.

**Ideas:**
- Season-specific models (summer/winter)
- Weekday vs weekend models
- Holiday-aware models

---

### [Admin] Admin Tools

**Goal:** Add admin tooling for system maintenance.

**Features:**
- Force ML Retrain button
- Clear Learning Cache button  
- Reset Learning for Today button (Debug tool)

---

## 📝 Verified as Done (Not Moved to Changelog)

*These were backlog ideas that have been verified as already implemented. They were never formal revisions, so they don't exist in CHANGELOG_PLAN.md:*

| Item | Status | Notes |
|------|--------|-------|
| A25 - Manual Plan Simulate | SCRAPPED | Planning tab deprecated, no longer relevant |
| A27 - ML Training Scheduler | ✅ DONE | Implemented in `scheduler.py` with catch-up logic |
| Smart Thresholds | ✅ DONE | Implemented as Rev A20 (exists in changelog) |
| Sensor Unification | ✅ DONE | All sensors now in `config.yaml`, none in `secrets.yaml` |
| Error Handling audit | ✅ DONE | Implemented as Rev F4 Health Check |

