# Darkstar Energy Manager: Backlog

This document contains ideas, improvements, and tasks that are not yet scheduled for implementation.

---

## 🤖 AI Instructions (Read First)

1.  **Naming:** Use generic names (e.g., `Settings Cleanup`, `Chart Improvements`) until the item is promoted.

2.  **Categories:**
    - **Backlog** — Concrete tasks ready for implementation
    - **On Hold** — Paused work with existing code/design
    - **Future Ideas** — Brainstorming, needs design before implementation

3.  **Format:** Use the template below for new items.

### Backlog Item Template

```
### [Category] Item Title

**Goal:** What we want to achieve.

**Notes:** Context, constraints, or design considerations.
```

---

## 📋 Backlog

### 📥 Inbox (User Added / Unsorted)

<!-- Add new bugs/requests here. AI should wipe the item after processing into a OpenSpec change. -->

#### [HA/Performance] Slim Down Home Assistant History Fetches

**Goal:** Reduce the latency of `/api/ha/average` (and related HA history reads), which still takes ~1.3s on a cache miss. The cost is the HTTP round-trip to Home Assistant's `/api/history/period` plus parsing a large, maximal-detail response — not CPU on our side.

**Notes:** Discovered 2026-06-17 while verifying `dashboard-performance-pass` (which targeted CPU-bound work and correctly did not change this I/O-bound path). The history requests fetch maximal detail: `backend/api/routers/ha.py:_fetch_ha_history_avg` (lines 39-40) and `backend/core/ha_client.py:get_load_profile_from_ha` both set `significant_changes_only: False` and `minimal_response: False`. Options to try: (a) set `minimal_response: True` and/or `no_attributes: True` to shrink the payload, (b) set `significant_changes_only: True` where attribute precision isn't needed, (c) lengthen/tune the existing 60s cache. Validate that the averaging/step-integration math still produces correct results with the reduced data before/after. Low priority — it has a 60s cache and no longer blocks the dashboard (the CPU serialization that did is fixed).

---

#### [Specs] Fix 5 Pre-Existing OpenSpec Validation Failures

**Goal:** Make `openspec validate --specs` pass cleanly. Five spec files fail format validation (independent of any feature work — the capabilities are implemented; only the spec docs don't conform). Fix each by adding the missing normative `SHALL`/`MUST` wording and/or at least one `#### Scenario:` block per requirement:
- `startup-wizard` — all 5 requirements lack a `SHALL`/`MUST` keyword; Purpose section is too brief (<50 chars).
- `sensor-configuration` — requirements #4 and #5 lack a `SHALL`/`MUST` keyword.
- `aurora-corrector` — requirement #1 lacks both a `SHALL`/`MUST` keyword and a scenario.
- `executor` — requirements #2 and #3 have no `#### Scenario:` block.
- `planner` — requirement #5 has no `#### Scenario:` block.

**Notes:** Discovered 2026-06-17 during verification of the `dashboard-performance-pass` change. Pre-existing failures, unrelated to that change (not in its diff). These are hard errors (they fail even without `--strict`), but they are documentation/lint issues only — no code is broken. Files live in `openspec/specs/<name>/spec.md`. Each requirement needs a `### Requirement:` line containing SHALL/MUST plus ≥1 `#### Scenario:` (level-4 header) with WHEN/THEN bullets.

---

#### [Planner/API] `/api/simulate` Fails with `'dict' object has no attribute 'iterrows'`

**Goal:** Fix the `POST /api/simulate` endpoint, which currently returns `{"status":"error","message":"'dict' object has no attribute 'iterrows'"}` instead of running a simulation. Something passes a plain `dict` where a pandas DataFrame is expected (`.iterrows()` called on it).

**Notes:** Discovered 2026-06-16 during verification of the `battery-cycle-cost-floor` change. Pre-existing and unrelated to that change — the simulate path is not touched by it, and the main planner cycle runs fine (full Kepler plan succeeds at startup). Scope is `/api/simulate` only. Start by tracing where the simulate handler builds/forwards its input data and find the spot that should be a DataFrame but is a dict.

---

#### [Tooling] Deliberate Dependency Upgrade + Tight Pinning Pass

**Goal:** Bring all dependencies up to current versions in a controlled pass, then pin them so CI and local always resolve identically. Covers: runtime deps (`requirements.txt`, currently loose `>=` pins), dev tools (`pyright` is held at 1.1.408 — one behind latest; `ruff` at 0.15.5; `pytest` et al. still loose), `pnpm` (pinned to 9 in the Dockerfile to dodge pnpm 10's Node-22 `node:sqlite` requirement), and the Node version in the add-on `Dockerfile`.

**Notes:** Carved out of the `harden-ci-and-tests` work (2026-06-10). That change pinned only the tools that were actively breaking CI (`ruff`, `pyright`) and matched `pnpm`/Node to the known-good versions — it intentionally did NOT chase "latest everywhere," because the bug was *version mismatch between local and CI*, not staleness. A real upgrade is its own change: bump deliberately, run `scripts/ci_local.sh` after each step, and fix anything newer/stricter versions flag (especially pyright in strict mode). Consider upgrading the add-on Node so `pnpm` can move to 10. Decide whether to keep `requirements*.txt` or migrate deps into `pyproject.toml` + a real `uv.lock` (the current lock is empty) for first-class locking.

---

#### [Testing] Frontend Test Coverage Gap

**Goal:** Establish meaningful automated test coverage for the frontend. Currently only ~2 tests exist for ~100 components.

**Notes:** Flagged during the stabilization review (2026-06, finding #3). That review was scoped backend-only, so the gap was recorded but never actioned. The backend CI/test floor is being addressed by the `harden-ci-and-tests` change; the frontend remains a separate, unaddressed follow-up. Needs a decision on framework/scope before promotion (which critical components/flows to cover first).

---

#### [Price Forecast / S-Index] Calibrate `RISK_PRICE_KW_FRACTION` Against Real Price Data

**Goal:** Revisit the risk-fraction constants `{1: 0.15, 2: 0.12, 3: 0.10, 4: 0.05, 5: 0.02}` in `planner/strategy/s_index.py` after Module 3 (price-forecasting-module-3) has been live in production for 2–4 weeks and a meaningful sample of real positive-spread events has been observed. Determine whether the resulting floor adjustments match expected behavior or need tuning.

**Notes:** Added 2026-04-25 as part of price-forecasting-module-3. The fractions were chosen by reasoning about reasonable behavior for Swedish price ranges, not measured against historical Nordpool data. Sample evaluation criteria: (a) does Risk 1 (Safety) actually hoard appropriately during real winter spikes? (b) is Risk 5 (Gambler) correctly under-reactive? (c) are mid-spread events (~1–2 SEK/kWh) producing floor changes the user intuitively agrees with? Use `s_index_debug` log entries and `strategy_log` events as the data source.

---

#### [Price Forecast / S-Index] Explore Top-2-Average vs Pure Peak for Upcoming Price Signal

**Goal:** Investigate whether `calculate_price_floor_addon()` should use the top-2 daily average instead of the pure peak (`max`) across D+1–D+7 to compute `peak_upcoming_sek`. The pure-peak approach is sensitive to a single inaccurate D+5/D+6/D+7 forecast day; a top-2 average dampens that without losing strong-spike sensitivity.

**Notes:** Added 2026-04-25 as part of price-forecasting-module-3. Module 3 ships with pure peak for KISS reasons (simpler, easier to debug). The 80% capacity cap and the trailing-14-day average already provide some protection against runaway addons from a single bad forecast day. Revisit only if real-world observation shows the pure peak is producing unwarranted floor increases on bad-forecast days. Trivial code change if needed.

---

#### [Planner] Multiple Heating Sources/Deferrable Loads

**Goal:** Support control for multiple distinct heating sources (e.g., HVAC + Water Heater + Floor Heating) independently. A simple switch per each source to enable/disable it, and then the planner will decide when to turn them on/off based on the optimization problem. We need parameter for the kW consumption of each source and time/kWh goal.

**Notes:** Currently limited to a single water heater channel.

---

#### [Learning] Per-Device Load Forecasting

**Goal:** Train per-device load models (EV, water heater) instead of aggregated forecasts. Enables the planner to predict per-device consumption patterns (e.g., Tesla charges faster than Leaf, upstairs heater runs more at night).

**Notes:** Currently `ev_charging_kwh` and `water_kwh` in `slot_observations` are aggregated across all devices. Per-device energy recording (added in multi-device-ev-chargers change) provides the data foundation. Requires extending Aurora/Reflex models to accept device ID as a feature, and per-device forecast output in the pipeline. Not blocking for multi-device scheduling — the planner uses real-time sensor state, not forecasts, for per-device decisions.

---

#### [Price Forecast] Mock Script Inserts Timezone-Naive Timestamps

**Goal:** Fix `scripts/insert_mock_price_forecasts.py` line 52 to include timezone offset in `slot_start`. Currently uses `strftime("%Y-%m-%dT%H:%M:%S")` which produces `2026-03-30T00:00:00` (no timezone), while production code produces `2026-03-30T00:00:00+02:00`. This causes join mismatches with `slot_observations` (which always includes timezone).

**Notes:** Discovered during price-forecast-ui-enhancements verification (2026-04-08). Not a production bug — only affects dev/test data. Fix: use `.isoformat()` on a timezone-aware datetime instead of `strftime`. Also consider adding the same fix to `issue_timestamp` on the same line.

---

#### [Price Forecast] Discontinuity Between Actual and Forecasted Prices at Midnight

**Goal:** Investigate and fix the large price spike at the boundary between historical actuals and forecasted prices (e.g., actual 0.16 at 23:45 jumping to forecast 0.70 at 00:00). The forecast should be continuous with recent actuals, especially for the D+1 boundary.

**Notes:** Discovered during price-forecast-ui-enhancements verification (2026-04-08). The LightGBM price model doesn't use the most recent actual spot price as an input feature — it relies on lagged averages (`price_lag_1d`, `price_lag_7d`, `price_lag_24h_avg`) which smooth out the current price level. Possible improvements: (a) add a `price_last_known` feature using the most recent `slot_observations.export_price_sek_kwh` value, (b) apply a blending/stitching function at the actual-to-forecast boundary that smoothly transitions from the last known actual to the model's prediction over a few hours, (c) bias-correct the forecast series to anchor to the last known actual.

---

#### [Price Forecast] Sawtooth Pattern in Price Chart

**Goal:** Investigate and fix the sawtooth/zigzag pattern visible in the Aurora Forecast Horizon price chart before certain timestamps (e.g., "Tue 00:15"). Determine whether this is a data artifact from mock/seed data or a model interpolation issue with overlapping forecast runs producing different values for the same slots.

**Notes:** Observed during price-forecast-ui-enhancements verification (2026-04-08). Could be caused by: (a) mock data inserted via `scripts/insert_mock_price_forecasts.py`, (b) overlapping forecast runs with slightly different predictions for the same 15-min slots, (c) model interpolation artifacts from sparse training data. Check raw DB data first before assuming code bug.

---

#### [Price Forecast] Improve Price Alert Accuracy

**Goal:** Review and improve the rule-based price alert thresholds in `backend/api/routers/analyst.py` (`_get_price_advice()`). Current alerts ("cheapest day ahead" at 30% threshold, "prices rising", "cheap overnight" at 25% threshold) may fire on noise or stale forecast data, producing alerts that don't match observed reality.

**Notes:** Observed during price-forecast-ui-enhancements verification (2026-04-08). The alerts are dynamically generated from real forecast data (not hardcoded), but the simple percentage thresholds may need tuning. Consider: (a) requiring minimum absolute price difference, not just percentage, (b) filtering out stale forecast data before computing alerts, (c) confidence-weighting alerts based on model accuracy (d1_mae).

---

#### [Dashboard] Reorganize and Declutter Dashboard Layout

**Goal:** Audit all dashboard cards for redundancy, oversized elements, and poor information hierarchy. Redesign the layout so the most actionable information is prominent and secondary data is accessible but not dominant.

**Notes:** Raised after adding EV multi-day charging card to the Energy Resources section. The dashboard has grown organically and likely has cards that overlap in purpose or consume too much space relative to their value. Should be tackled as a standalone UX pass after the EV multi-day feature ships, so the final card set is known before optimizing layout.

---

### 💡 Future Ideas (Brainstorming)

#### [S-Index] `max_safety_buffer_pct` Cap Suppresses Risk-Level Differentiation

**Goal:** Make `max_safety_buffer_pct` risk-level-aware so that Risk 1 (Safety) users genuinely get a higher safety floor ceiling than Risk 3 (Neutral) users during high-deficit periods.

**Notes:** Currently `max_safety_buffer_pct` defaults to 20% of battery capacity and does NOT vary by risk level. On days with moderate-to-high temporal deficit, most users hit the 20% cap regardless of risk level — meaning the floor is effectively identical for Risk 1 and Risk 3 users. The risk differentiation via `RISK_CONFIG` margins and `min_buffer_pct` in `s_index.py` only activates on easy/sunny days when the deficit is small enough to stay below the cap. Potential fix: make the cap a per-risk-level value (e.g., Risk 1: 30%, Risk 3: 20%, Risk 5: 15%). Discovered during Module 3 (S-Index Price Awareness) design — the Module 3 price addon deliberately bypasses this 20% cap by being additive on top of the already-capped base floor, bounded separately at 80% of capacity.

---

#### ~~[EV] Multi-Day EV Charging Planning~~ → PROMOTED

Promoted to active changes: `price-forecasting-module-4` (backend) and `price-forecasting-module-5` (UI + HA integration).

---
