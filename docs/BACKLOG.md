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

#### [Schedule] Schedule File Write Integrity

**Goal:** The executor should never read a half-written `schedule.json`.

**Notes:** Observed once in production on 2026-09-14: `executor.engine | Failed to load schedule: Expecting ':' delimiter: line 6674 column 19 (char 196756)`. The file is ~200 KB, so a reader can observe a partial write. Likely a non-atomic write (write-in-place rather than write-to-temp-then-rename). Note that `darkstar.config_migration` already logs `[CONTAINER] Atomic replace not possible on this mount, falling back to direct copy (last resort)` for `config.yaml`, so the bind mount may block `os.replace` for this file too — check whether the same fallback applies and what the safe pattern is on that mount. Single occurrence in 7 days of retained logs; the executor recovers on the next tick, so impact is one skipped schedule load.

#### [Database] Concurrent Planner Run DB Contention

**Goal:** Overlapping planner runs should not produce `database is locked` errors.

**Notes:** Observed on 2026-09-17 22:15 during an overlapping run: `executor.engine | Executor tick failed: (sqlite3.OperationalError) database is locked [SQL: INSERT INTO execution_log ...]` and `backend.battery_cost | Failed to update battery cost: (sqlite3.OperationalError) database is locked`. Trigger: a manual `POST /api/run_planner` fired while a scheduled run was still in flight — `darkstar.services.planner` logged `Planner already running, skipping concurrent request`, so the guard rejected the second planner run, but the surrounding writes still collided. The DB is WAL mode, so this is write-write contention, not reader blocking. Consider a busy_timeout and/or serializing these writers. Related existing capability: `database-concurrency-safety`.

---

## 🔧 Improvements

<!-- Empty -->

---

## ✨ New Features

<!-- Empty -->

---

## 💡 Future Ideas / Deferred

<!-- Empty -->
