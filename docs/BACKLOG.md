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

#### [Price Forecast / S-Index] Calibrate `RISK_PRICE_KW_FRACTION` Against Real Price Data **(needs production data)**

**Goal:** Revisit the risk-fraction constants `{1: 0.15, 2: 0.12, 3: 0.10, 4: 0.05, 5: 0.02}` in `planner/strategy/s_index.py` after Module 3 (price-forecasting-module-3) has been live in production for 2–4 weeks and a meaningful sample of real positive-spread events has been observed. Determine whether the resulting floor adjustments match expected behavior or need tuning.

**Notes:** Added 2026-04-25 as part of price-forecasting-module-3. The fractions were chosen by reasoning about reasonable behavior for Swedish price ranges, not measured against historical Nordpool data. Sample evaluation criteria: (a) does Risk 1 (Safety) actually hoard appropriately during real winter spikes? (b) is Risk 5 (Gambler) correctly under-reactive? (c) are mid-spread events (~1–2 SEK/kWh) producing floor changes the user intuitively agrees with? Use `s_index_debug` log entries and `strategy_log` events as the data source.

---

#### [Price Forecast / S-Index] Explore Top-2-Average vs Pure Peak for Upcoming Price Signal **(needs production data)**

**Goal:** Investigate whether `calculate_price_floor_addon()` should use the top-2 daily average instead of the pure peak (`max`) across D+1–D+7 to compute `peak_upcoming_sek`. The pure-peak approach is sensitive to a single inaccurate D+5/D+6/D+7 forecast day; a top-2 average dampens that without losing strong-spike sensitivity.

**Notes:** Added 2026-04-25 as part of price-forecasting-module-3. Module 3 ships with pure peak for KISS reasons (simpler, easier to debug). The 80% capacity cap and the trailing-14-day average already provide some protection against runaway addons from a single bad forecast day. Revisit only if real-world observation shows the pure peak is producing unwarranted floor increases on bad-forecast days. Trivial code change if needed. Rides along with the `RISK_PRICE_KW_FRACTION` calibration session — same data, same analysis.

---

#### [Price Forecast] Improve Price Alert Accuracy **(needs production data)**

**Goal:** Review and improve the rule-based price alert thresholds in `backend/api/routers/analyst.py` (`_get_price_advice()`). Current alerts ("cheapest day ahead" at 30% threshold, "prices rising", "cheap overnight" at 25% threshold) may fire on noise or stale forecast data, producing alerts that don't match observed reality.

**Notes:** Observed during price-forecast-ui-enhancements verification (2026-04-08). The alerts are dynamically generated from real forecast data (not hardcoded), but the simple percentage thresholds may need tuning. Consider: (a) requiring minimum absolute price difference, not just percentage, (b) filtering out stale forecast data before computing alerts, (c) confidence-weighting alerts based on model accuracy (d1_mae).

---

## ✨ New Features

#### [EV] Per-Charger Delivered-Energy Attribution

**Goal:** Attribute delivered EV energy per charger instead of using the aggregate `slot_observations.ev_charging_kwh`. Needed for honest progress display (today every charger shows the household EV total as its own `delivered_kwh`) and for SoC-less requirement tracking with more than one charger.

**Notes:** From the post-merge review of price-forecasting-module-4 (2026-07-09). The `ev-goal-charging-fixes` change gates the aggregate-based fallback to single-charger setups; this item lifts that limitation. Per-device energy recording foundations exist (see the related Future Ideas item "[EV] Full Support for Chargers Without a SoC Sensor" and "[Learning] Per-Device Load Forecasting" — data is recorded per device in the multi-device change). Likely approach: per-charger energy sensors or integrating each charger's power sensor. Only matters in practice with more than one configured charger — relevant for other users even though the maintainer runs one. Needs a design discussion (sensor strategy) before promotion.

---

#### [UI] Settings Search / Command Palette (Ctrl+K)

**Goal:** Implement a global quick search bar or keyboard command palette at the top of the settings page.

**Notes:** Allows users to jump directly to any configuration field (e.g. "Main Fuse") across the System, EV, Water, Load Balancing, UI, and Advanced tabs without manual navigation.

---

#### [UI] Live Load-Balancer Status Overlay on Dashboard

**Goal:** Display a live phase current (L1, L2, L3) bar graph and overload status overlay on the main dashboard.

**Notes:** Highlights active load shedding, EV charger throttling, or stale-sensor fallback alerts, including a one-click manual bypass/override control. Consider designing together with (or right after) the Dashboard Reorganize/Declutter pass so a new card isn't added and then immediately reorganized.

---

#### [Learning] Per-Device Load Forecasting

**Goal:** Train per-device load models (EV, water heater) instead of aggregated forecasts. Enables the planner to predict per-device consumption patterns (e.g., Tesla charges faster than Leaf, upstairs heater runs more at night).

**Notes:** Currently `ev_charging_kwh` and `water_kwh` in `slot_observations` are aggregated across all devices. Per-device energy recording (added in multi-device-ev-chargers change) provides the data foundation. Requires extending Aurora/Reflex models to accept device ID as a feature, and per-device forecast output in the pipeline. Not blocking for multi-device scheduling — the planner uses real-time sensor state, not forecasts, for per-device decisions.

---

## 💡 Future Ideas / Deferred

#### [Planner/Balancing] Planner Awareness of Sustained Phase Overload (Considered & Deferred 2026-07-06)

**Goal:** Make the planner aware that the load balancer is persistently capping an EV charger below its planned amps, so plans stop assuming energy the hardware keeps refusing. Today the planner has no concept of the per-phase fuse constraint: under a *sustained* phase overload, every replan asks for full amps again, the balancer throttles it again every tick, and the two never converge — the car is delivered undercharged with the planner none the wiser (the only feedback is the eventual lower SoC read on the next planner run).

**Notes:** Considered and deferred during the load-balancing UX/reconciliation discussion (2026-07-06). Deferred because feeding a dynamic constraint into a 30-min-horizon plan is inherently shaky: any average of "recent available headroom" goes stale the moment the household load changes (dinner ends → full 16 A is available again 5 minutes later), so a naive feed would under-plan as often as it helps. The shipped mitigation is (a) live SoC re-read every planner run and (b) an early-replan trigger after sustained throttling (part of the load-balancing completion change). Revisit only if real-world execution logs show chronic, long-lived phase congestion that the SoC feedback loop demonstrably fails to absorb. If revisited, candidate designs: a decaying per-charger "achievable amps" estimate fed as a solver cap, or planning only the *committed* portion of EV energy against observed headroom percentiles.

---

#### [EV] Full Support for Chargers Without a SoC Sensor (Deferred 2026-07-06)

**Goal:** Make EV charge planning work honestly for chargers/cars with no SoC sensor. Today `soc_percent` silently defaults to `0.0` when unconfigured (`backend/core/ha_client.py`), so the planner sees the same assumed SoC every run — it can never detect charging progress or a balancer-throttling shortfall. Worse, with `battery_capacity_kwh` also defaulting to `0.0`, the solver's incentive buckets collapse and no charging is scheduled at all.

**Notes:** Deferred during the load-balancing completion discussion (2026-07-06) — modern EVs generally expose SoC, so the config-time warning shipped in that change ("Darkstar can't track charging progress for this car") covers the realistic case of a *forgotten* sensor rather than a truly absent one. If full support is ever wanted: energy-counted sessions (integrate delivered kWh from the charger's energy sensor against a user-stated target kWh) would substitute for SoC-based need tracking. Delivered per-session energy is already recorded (`slot_observations.ev_charging_kwh`), so the data foundation exists.

---

#### [Executor/Balancing] Battery-Assist for Load Balancing (Considered & Deferred 2026-07-05)

**Goal:** During a main-fuse stress event, command a short house-battery discharge burst to shave the grid import peak *before* (or instead of) throttling the EV charge current — so the EV keeps charging at full speed while e.g. sauna/oven peaks pass.

**Notes:** Explicitly considered and **deferred** during planning of the universal load balancing + EV current control changes (2026-07-05). Do not implement unless a revisit trigger fires. Context for a fresh session:

- **Depends on:** the universal load balancing change (per-phase fuse guard in the executor, `system.grid.main_fuse_a`, EV variable current control) and the excess-PV priority dispatch change being live in production first.
- **Why deferred:**
  1. The user's Deye inverter in "Zero Export To CT" mode already ramps battery discharge to cover house load automatically within ~1–2 s at firmware level — implicit battery assist already exists whenever Darkstar has the battery in a discharge-allowed mode.
  2. The one case where it does NOT happen is deliberate: the executor's EV "source isolation" rule forces `discharge_kw=0` while the EV charges, because the user does not want the house battery (indirectly) feeding the EV. Battery-assist would poke a hole in that rule.
  3. Fuse protection doesn't need it: with 5 s grid sensors and a 5 s executor tick, the EV throttles within ~10 s, and fuses tolerate modest overloads for minutes.
  4. Phase physics: fuse stress is usually one overloaded phase; a 3-phase inverter discharge spreads relief across all phases, so only ~1/3 of the discharge helps the stressed phase.
- **Strongest genuine use case if revisited:** when per-phase headroom drops just below the EV's 6 A minimum, a small battery burst could hold the EV at 6 A and avoid pause/resume cycling (anti-flap timers from the load balancing change mitigate this already).
- **Revisit triggers:** (a) Sweden's effekttariff returns (peak shaving gains direct monetary value, feature changes character entirely), or (b) production experience after the two changes shows EV charging being throttled/paused annoyingly often. Reopen with real data (execution logs showing balancer interventions), and decide battery-vs-EV priority + source-isolation exception rules at that point.

---

#### [S-Index] `max_safety_buffer_pct` Cap Suppresses Risk-Level Differentiation

**Goal:** Make `max_safety_buffer_pct` risk-level-aware so that Risk 1 (Safety) users genuinely get a higher safety floor ceiling than Risk 3 (Neutral) users during high-deficit periods.

**Notes:** Currently `max_safety_buffer_pct` defaults to 20% of battery capacity and does NOT vary by risk level. On days with moderate-to-high temporal deficit, most users hit the 20% cap regardless of risk level — meaning the floor is effectively identical for Risk 1 and Risk 3 users. The risk differentiation via `RISK_CONFIG` margins and `min_buffer_pct` in `s_index.py` only activates on easy/sunny days when the deficit is small enough to stay below the cap. Potential fix: make the cap a per-risk-level value (e.g., Risk 1: 30%, Risk 3: 20%, Risk 5: 15%). Discovered during Module 3 (S-Index Price Awareness) design — the Module 3 price addon deliberately bypasses this 20% cap by being additive on top of the already-capped base floor, bounded separately at 80% of capacity.
