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

#### [Security] Optional Authentication For Exposed Port 5000

**Goal:** Offer optional authentication for users who expose port 5000 beyond a trusted LAN. Local-only or reverse-proxy-with-login setups need no login.

**Notes:** Priority P2. Status Confirmed. Browser cross-site writes are blocked by `beta-exit-hardening`, but non-browser clients on the network still have no authentication: 34 write routes and 74 GET routes (executor control `backend/api/routers/executor.py:112-536`, config writes `config.py:137`, `:2023`, HA writes `ha.py:299`, `:343`, EV actions `ev.py:126`, `:771`, `:811`, updater apply `updater.py:76`). Listens on `0.0.0.0:5000` (`darkstar/run.sh:356`, `scripts/docker-entrypoint.sh:125`); Docker publishes `5000:5000` (`docker-compose.yml:14-15`); the add-on publishes 5000 besides ingress (`darkstar/config.yaml:30-38`). Source: beta-exit audit 2026-11.

#### [Executor] Idle Fallback Differs Per Inverter Profile

**Goal:** Verify that the idle fallback used when there is no valid schedule is the intended safe state for every inverter profile.

**Notes:** Priority P2. Status Needs verification. `SLOT_FAILURE_FALLBACK` (`executor/override.py:183-197`) selects idle, but the result differs per profile in `profiles/*.yaml`: deye allows 15 A discharge, sungrow uses self-consumption plus 10 W, generic is `CONFIGURE_ME`. Not verified intentional. Alerting for a missing or stale schedule is handled by `beta-exit-hardening`. Source: beta-exit audit 2026-11.

#### [Database] Upgrades Cannot Be Undone (Backup And Rollback)

**Goal:** Make every migration recoverable with a consistent, pruned DB backup and an updater rollback.

**Notes:** Priority P0 (beta exit). Status Confirmed. Docker start-up backup is a plain `cp` of the live DB without WAL checkpoint, runs every start, never pruned (819 MB each), and migrates anyway if it fails (`scripts/docker-entrypoint.sh:81-92`). Add-on runs `alembic upgrade head` with no backup (`darkstar/run.sh:327-340`). No downgrade is invoked anywhere; `docs/OPERATIONS.md:39` says no automatic backup. Source: beta-exit audit 2026-11.

#### [Database] Database Grows Forever (Retention And Vacuum)

**Goal:** Prune old rows and reclaim space so the planner database stops growing without bound.

**Notes:** Priority P0 (beta exit). Status Confirmed. `ExecutionLog.cleanup_old_records` (`executor/history.py:279`) has no call sites outside tests; `history_retention_days` is parsed but unused (`executor/config.py:1432`). Six tables unpruned: `slot_observations`, `slot_forecasts`, `slot_plans`, `planner_debug`, `execution_log`, `price_forecasts`. No `VACUUM`. Local `data/planner_learning.db` is 819 MB. Source: beta-exit audit 2026-11.

#### [Updater] Updater Integrity, Pinned Origin And Rollback

**Goal:** Make updates verifiable and recoverable, and keep apply from being a root-on-host path.

**Notes:** Priority P1 (beta exit); P0 if port 5000 is reachable (see optional authentication item). Status Confirmed. Unauthenticated `/api/updater/apply` and `PUT /api/updater/channel` (`backend/api/routers/updater.py`); browser cross-site writes are blocked by OpenSpec change `beta-exit-hardening` (Sec-Fetch-Site guard), but any non-browser client that can reach the port can still call them. Only the git ref is verified: no tag or commit signature check, origin URL not pinned (`updater/repo.py:63-66`), tags force-fetched, and the fetched Dockerfile is built with `/var/run/docker.sock` mounted (`docker-compose.yml:57`) = root on host. Caller can only pick dev/stable. Add `git verify-tag` against a pinned key and assert origin is `github.com/ergetie/darkstar`. No rollback after a migrated DB or unhealthy start (`updater/service.py:361-364`); apply flow at `service.py:309-348`. Source: beta-exit audit 2026-11.

#### [Diagnostics] Diagnostics Bundle Has No Redaction

**Goal:** Redact secrets and sensitive data from the diagnostics bundle before users post it publicly.

**Notes:** Priority P1 (beta exit). Status Confirmed. `/api/system/diagnostics` has no login and bundles raw `config.yaml`, full log, full DB and `schedule.json` with no redaction (`backend/api/routers/system.py:481-577`); `secrets.yaml` is excluded, HA token never logged. P2: HA URL is logged. Users post bundles on Discord. Source: beta-exit audit 2026-11.

#### [Planner] Price Fetch Failure Handling

**Goal:** Handle price fetch failures gracefully with fallback, correct classification and notification.

**Notes:** Priority P1 (beta exit). Status Confirmed (traced 2026-11-18). `backend/core/prices.py:16-139` catches all errors, returns `[]`, 10s timeout, no retries, no last-good cache fallback (TTL 3600s). Planner fails, `schedule.json` untouched; executor follows the old plan until 2h stale, then idle. Gaps: (P1) tomorrow fetch failing after 13:00 discards today's good prices (`prices.py:78-94`, same try); (P1) add last-good-cache fallback; (P1) empty prices likely raise IndexError at `planner/pipeline.py:1736`, classified UNKNOWN instead of PRICES_UNAVAILABLE (not verified by running): check prices at start of `generate_schedule`; (P2) no push notification for planner failures, only WebSocket `planner_error` (`planner_service.py:421`); (P2) after 13:00 with no tomorrow data the cache is invalidated every call, causing repeated 10s fetches. Source: beta-exit audit 2026-11.

#### [Planner] Price Reserve Flaps On Biased D+1 Price Forecast

**Goal:** Stop the price reserve from raising the SoC target on a D+1 price gap that is smaller than the forecast's own error.

**Notes:** Status Reported, not verified. Reporter's D+1 forecast bias is +0.38 SEK/kWh (`d1_mae` 0.52, 10 days). On 2026-11-18 03:18 the reserve raised the SoC target by 7.7 kWh on a 0.24 SEK/kWh gap (3.60 vs 3.36) and flipped on/off at 03:18, 05:19, 05:49, 06:05 and 06:20. Suggested: subtract the rolling bias, or require the gap to exceed recent |bias|/MAE before activating. Source: GitHub #8 (Cm0n89), "Other findings".

#### [Planner] Missing Slot At Nordpool To Forecast Boundary

**Goal:** Make the schedule continuous where real Nordpool prices end and forecast prices begin.

**Notes:** Status Reported, not verified. `/api/schedule` jumped from 2026-11-19 23:45 to 2026-11-20 00:15. Reporter suspects how `days_ahead` is assigned to the 00:00 slot in `price_forecasts`. Source: GitHub #8 (Cm0n89), "Other findings".

#### [Benchmark] Battery Benchmark Infeasible On Full-Capacity Days

**Goal:** Find out why the battery benchmark is infeasible on days that use nearly the whole battery, and fix it.

**Notes:** Status Reported, not verified. Infeasible on 7 of 30 days for the reporter (incl. 2026-11-15 to 11-18), mostly days with `implied_capacity_kwh` ≥ 10.1 (capacity 10.24 kWh, min SoC 5 %). Reporter's 2026-11-09 and 11-10 `not_clean_recording` days may come from the missing backfill fixed in the #8 change. Source: GitHub #8 (Cm0n89), "Other findings".

#### [Executor] Detect Inverter Mode Reverts And Power Mismatch

**Goal:** Warn when the inverter does not follow the commanded mode or power.

**Notes:** Status Reported, not verified; probably integration-side. Fronius GEN24: during grid charging `storage_control_mode` reverted from "Charge from Grid" to "Discharge Limit" 20 s to 17 min after each write, with no HA context; 3.3 kW commanded, ~0.4–0.6 kW delivered (01:00–02:00). The executor could detect commanded vs actual mismatch and warn. Source: GitHub #8 (Cm0n89), "Other findings".


---

## 🔧 Improvements

#### [Learning] Remove Dead Error-Correction Config And Models

**Goal:** Remove the leftovers of the removed error-correction feature so the UI and API stop showing a broken feature.

**Notes:** Status Confirmed 2026-11-19 (code read). `learning.error_correction_enabled` and `automation.ml_training.error_correction_enabled` are read nowhere in code (only docs and archived specs; the archived proposal kept them for backward compatibility). `/api/learning/training-status` still lists `pv_error.lgb` and `load_error.lgb` from 2026-03-13 (reported, not verified). Needs a config migration that drops the keys. Source: GitHub #8 (Cm0n89), "Other findings".

#### [Settings] Warn About Out-Of-Range And Learning-Contradicted Settings

**Goal:** Tell the user when a setting is outside the range Darkstar's own learning would ever choose, or contradicts what the recorded data shows, and what it is likely costing them.

**Notes:** Found 2026-10-06 (cmon89): `forecasting.pv_confidence_percent` was 60 while Reflex only moves it within 70–120 (`backend/learning/reflex.py:22`) and his forecasts were 96 % accurate over 30 days (PV 938 actual vs 905 forecast). Nothing warned him. A replay estimated 60 % vs 83 % at ~53 kr over 25 days. His `learning.max_daily_param_change.pv_confidence_percent` was also 60 (default 1.0). Must cover every Reflex-tuned parameter (bounds table in `reflex.py`) and similar settings, e.g. max-daily-change values far from defaults. Harmless leftovers (e.g. an enabled `water_heaters` entry with `has_water_heater: false`, which the planner ignores) get at most a one-time info note, not a warning.

#### [Release] Stable Channel Is Dead, No Promotion Gate

**Goal:** Revive the stable channel with a soak period between dev and stable.

**Notes:** Priority P0 (beta exit). Status Confirmed. Last tag `v2.7.1-beta` (2026-09-26); main is 110 commits ahead. `darkstar/config.yaml` (stable) still 2.7.1-beta, while `darkstar-dev/` gets an image on every push. Discord users run darkstar-dev, so every push lands on them directly. Source: beta-exit audit 2026-11.

#### [Release] High Fix Volume

**Goal:** Reduce regressions and release more regularly.

**Notes:** Priority P1 (beta exit). Status Confirmed. Last 90 days: 145 commits, 61 fixes, 37 features; fixes by area: executor 9, forecasting 7, settings 5, EV 5, config 3, updater 2, recording 2, load profile 2, battery 2. Only 2 releases (v2.7.0 09-18, v2.7.1 09-26). Source: beta-exit audit 2026-11.

#### [Support] Support Depends On One Person On Discord

**Goal:** Move support toward a structure that does not rely on one maintainer.

**Notes:** Priority P1 (beta exit). Status Confirmed. GitHub has 5 issues total (1 open: #6 Sungrow battery never discharges below 20 percent) and 1 PR. Last 100 Discord messages (2026-11-04 to 11-16): 8 distinct non-maintainer authors. Themes: EV planning and catch-up charging, water heater scheduling, flat or low load forecast, graph data stopping mid-day, cost vs supplier bill, requests for new inverter profiles and non-Nordpool price providers. Source: beta-exit audit 2026-11.

#### [Testing] Test Gaps (Updater, E2E)

**Goal:** Close the thinnest test gaps.

**Notes:** Priority P2 (beta exit). Status Confirmed. Updater has 1 test file and a run of recent fixes; no browser-level e2e (`tests/e2e/` has 2 files). Source: beta-exit audit 2026-11.

#### [Docs] Inverter Profiles Have No Tested Marker

**Goal:** Mark which inverter profiles are tested and correct the docs claims.

**Notes:** Priority P2 (beta exit). Status Confirmed. Profiles: Deye, Fronius, Sungrow and generic; none has a tested/untested field, yet README lists all as "Supported". The setup guide cheat sheet calls Solis, Huawei and GoodWe mode strings "verified" although no such profile exists. Source: beta-exit audit 2026-11.

#### [Repo] Repo Not Ready For Outside Contributors

**Goal:** Add community files and remove stray tracked files.

**Notes:** Priority P2 (beta exit). Status Confirmed. No CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md or issue template. Stray tracked files: `history_debug_dump.json`, `msg_bad`, `data/history.db`, `frontend/package.json.bak`, `conductor/` (13 files). Source: beta-exit audit 2026-11.

---

## ✨ New Features

#### [Debug] Planner Run Archive With UI Download

**Goal:** Keep every planning run's full inputs and plan (and planner/executor errors) for a set period, so past decisions can be replayed and shared for support; the user can download it from the Debug page and clear it.

**Notes:** Found 2026-10-06 (cmon89 investigation): past decisions could not be reconstructed. `schedule.json` already holds each run's full per-slot inputs (adjusted PV/load, prices) and plan, but is overwritten every run; `slot_plans`/`slot_forecasts` keep only the last value per slot; `debug.enable_planner_debug` stores only a 30-slot sample (`planner/output/debug.py`); the log rotates and is wiped on add-on restart. Verified that re-solving an archived `schedule.json` with the offline Kepler reproduces the real plan exactly (0/122 slots differ). Retention 60–90 days, gzip (~10 kB/run, ~0.5 MB/day). Include initial SoC, safety floor, config version, solver status. Storage location (DB vs files) to decide. Enables the automatic daily replay item. Temporary stand-in on the maintainer's prod since 2026-10-06: a root cron (every minute) gzips each new `schedule.json` into `/opt/darkstar/data/plan_archive/`, and `debug.enable_planner_debug: true` is set. Remove both when this item ships or the investigation (`ops/investigations/cmon-underperformance-2026-10-06.md`) no longer needs them.

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

#### [Planner] Nordic Support (NO/FI/DK)

**Goal:** Support Norwegian, Finnish and Danish price areas properly.

**Notes:** Deferred 2026-11-19 (Sweden-only for beta exit). Traced 2026-11-18: nordpool lib fetches these areas, but currency is hard-labelled SEK (`KPIStrip.tsx:33`, `:50`, `:97`; `_sek` names in `prices.py`), tax defaults are Swedish (`config.default.yaml:274-276`), weather/ML regions are SE only (`ml/regions.json`, `ml/weather.py:856-873`), frontend timezone hardcoded `Europe/Stockholm` (`ChartCard.logic.ts:43`, `lib/time.ts:10`), no price_area/currency validation. Revisit when a non-Swedish user asks.
