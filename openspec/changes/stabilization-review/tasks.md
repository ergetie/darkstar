# Tasks — Stabilization Review

> **Diagnose-only.** No application code, config, schema, or dependency changes. Output is documentation in this change directory only.
> **Resumability is per-phase/per-domain** (one checkbox = one resumable unit). Run each phase in a fresh session.
> **Every phase session:** read `design.md` → read `findings.md` → do only this phase (read-only on app code) → append findings → tick the checkbox → stop.

## 0. Phase 0 — Baseline & Freeze

- [x] 0.1 Run the full test suite locally; record pass/fail counts and any failures as findings (severity per rubric) → 1051 passed / 0 failed (Baselines section)
- [x] 0.2 Document the 3 stale in-progress changes (`price-forecasting-module-3/4/5`) as paused, with a one-line reason each → Finding #4
- [x] 0.3 Confirm findings #1–#3 are present and accurate; verify `findings.md` + severity rubric (`design.md` D2) are in place → done; #3 sharpened with 1051 baseline
- [x] 0.4 Capture a coverage map: which of `backend/ planner/ ml/ executor/` modules are well-tested vs untested (seed S4 findings for the biggest gaps) → Finding #5

## 1. Phase 1 — Anchor Diagnosis (diagnose only; code-first, no user data needed)

> Reframed: mechanisms are confirmable by reading code; real user data only *quantifies* magnitude (deferred). The PV resolution is an **architecture discussion**, captured as Open Questions in `findings.md`.

- [x] 1.1 PV: confirm by code read the absence of a magnitude clamp (only night-zeroing exists) → Finding #2 (corrected: `physics_kwh` IS a feature)
- [x] 1.2 PV: confirm Layer-A physics gaps — fixed efficiency, no temp derate, no inverter AC clip, crude POA → Finding #6
- [x] 1.3 PV: confirm cold-start mechanism — `min_samples=100` (~1 day) replaces seed with under-fit local model → Finding #7
- [x] 1.4 PV: record the architecture decisions as Open Questions (OQ1–OQ5); do NOT decide them here
- [x] 1.5 PV (RESOLVED BY DATA): the Layer-A-physics vs cold-start split is settled by `scripts/compare_pv_paths.py` (2026-06-04) — physics over-produces ~2.5× (89–124 kWh/day from 7.11 kWp, physically impossible); the ML residual cancels it for trained homes (operator MAE 0.12) and leaks for cold-start. Synthetic repro would only re-confirm this → not run. See findings "Data Confirmation" section + Finding #6.
- [x] 1.6 EV: confirm export-vs-charge economics by code (slot_ev_cost=0.0; export revenue positive; bucket reward < export price) → Finding #1 (worked example pending in 1.7)
- [x] 1.7 EV: worked numeric example (Cases A/B/C, SE4 ≈0.30 SEK/kWh spot) added to Finding #1; executor verified plan-driven with NO independent PV-surplus gate (`engine._control_ev_charger` obeys `slot.ev_charger_plans`; only autonomous action is a stop-only safety timeout) → S1 lives entirely in the Kepler objective

## 2. Phase 2a — Broad Pass (light read, fan out per domain)

- [x] 2.1 `ml/` broad pass — dead code, silent excepts, unguarded math, kWh/kW/0.25h confusion, stale REV-comments vs behavior → Findings #9, #10 (+ #11 partial)
- [x] 2.2 `planner/` broad pass — same checklist → Findings #11, #12, #14
- [x] 2.3 `executor/` broad pass — same checklist → Findings #8, #13, #14
- [x] 2.4 `backend/` broad pass — same checklist (incl. `core/`, `services/`, `learning/`, `loads/`, `strategy/`, `recorder.py`, `ha_socket.py`) → Finding #14 (ha_socket); no other concrete code bugs surfaced beyond known Findings #2/#5
- [x] 2.5 Consolidate Phase 2a findings; flag any S1/S2 for immediate attention → no new S1/S2 found; all Phase 2a findings are S3/S4

## 3. Phase 2b — Deep Behavior Dives (trace scenarios, risky domains)

- [x] 3.1 Forecasting — trace a full PV+load forecast end to end (beyond the anchor bug): quantile models, recency weighting, cold-start, multi-array summation → Findings #15, #16, #17, #18
- [x] 3.2 Solver economics — trace the full Kepler objective: wear/terminal-value/export-threshold/S-Index interactions, water + EV deferrable loads, infeasibility fallbacks → Finding #12 confirmed display-only; Findings #19, #20
- [x] 3.3 Executor control — trace mode-intent determination, override logic, EV/water commands, heartbeat safety, idempotency, shadow mode → Findings #21, #22, #23, #24
- [x] 3.4 Recorder / data-consistency — verify the "DB is SSOT" claims: base-load disaggregation, EV/water kWh via HA history vs snapshot fallback, slot aggregation edge cases (DST, gaps) → Findings #25, #26, #27, #28, #29
- [x] 3.5 Config migration — trace migration + persistence (atomic vs Docker bind-mount fallback), deprecated-key removal, ARC15 entity-centric conversion edge cases → Findings #30, #31, #32, #33

## 4. Phase 3 — Architecture Review

- [x] 4.1 Two-PV-estimator reconciliation: document the relationship between the open-meteo library forecast and the physics+ML hybrid; record the "which is truth / should one clamp the other" question (decision deferred to a solution session) → OQ5 updated (largely resolved by pv-open-meteo-baseline: open-meteo = baseline spine, hybrid = baseline + bounded ±25% residual, both clamped to physical ceiling)
- [x] 4.2 God files: assess `executor/engine.py` (~2035) and `actions.py` (~1244) for split candidates and risk concentration → Finding #36
- [x] 4.3 Async / threading / SQLite: review event-loop blocking risks, executor-thread vs async-service boundaries, WAL contention on `planner_learning.db` → Findings #37 (WAL), #38 (sync DB on event loop); MILP solve confirmed offloaded (to_thread), not a blocker
- [x] 4.4 Safety invariants: document what protects the battery/grid when a forecast or plan is wildly wrong (post-Emergency-Charge-removal); identify missing guardrails → Finding #35 + OQ6
- [x] 4.5 Data SSOT & boundaries: validate module boundaries (planner ↔ executor ↔ recorder ↔ ML) and any double-counting / source-of-truth ambiguity → OQ7 (synthesis of #12/#25/#26/#27/#29 + executor↔recorder slot_observations dual-write)

## 5. Wrap-up

- [ ] 5.1 Review `findings.md` for completeness; ensure every finding has severity, location, and a CONFIRMED/UNVERIFIED root cause
- [ ] 5.2 Group confirmed findings into proposed downstream bug-fix changes (note which to batch); leave as a recommendations section — do NOT create those changes here
