## Why

The operator wants high confidence that Darkstar is stable and free of behavior-affecting bugs before any new feature work starts. The June 2026 stabilization review was a *static* pass (code reading → 38 findings → 7 fix changes, 6 landed); what has never been done is verifying the system's *runtime* behavior: does the live system actually do what the code intends, day after day, with real hardware and real money on the line? Eight months of production telemetry (23k+ observation slots, 255k execution-log rows, daily data-quality records) exist and have never been systematically mined for defects.

## What Changes

- **Failure-mode catalog**: a ranked list of the most expensive things Darkstar can do wrong (financial, hardware, availability, data-integrity). Every other activity in this review traces back to defending one of these. Captured in `design.md`.
- **Evidence mining (diagnose-only)**: systematic analysis of the production database and logs over the full 8-month history — plan-vs-actual divergence, executor command failures, forecast error drift, recorder gaps/anomalies, exception patterns. Every anomaly becomes a numbered finding.
- **Invariant catalog, checked three ways**: explicit system invariants (energy accounting, SoC bounds, slot continuity, plan freshness, command idempotency), each checked (a) against historical data, (b) by tests, and (c) — for the subset that matters at runtime — continuously in production via new monitors.
- **Targeted adversarial code review** of the concentrated-risk surfaces only: the Kepler MILP objective (money math), executor command paths (hardware safety), unit/timezone boundaries, the dual-writer SQLite setup, config migration, and the frontend's `ChartCard`/data-layer fragility points.
- **Fault-injection matrix (tests/simulation only — never the live system)**: HA unreachable, missing/partial prices, sensor garbage/spikes, restart mid-slot, DST transitions, stale schedule. Verifies the system degrades safely.
- **Runtime invariant monitors** — the only application code this change ships: a small monitoring module that continuously evaluates the invariant catalog in production and raises a `SystemAlert` on violation, so stability stays verified through all future feature work.
- **Findings ledger** (`findings.md`, append-only, severity S1–S4): the review's primary output. All fixes are spun off as separate OpenSpec changes afterward — this change fixes nothing itself.

## Capabilities

### New Capabilities
- `runtime-invariant-monitors`: continuous production evaluation of system invariants (energy accounting, SoC bounds, slot continuity, plan freshness, executor command success) with alerting on violation.
- `fault-injection-testing`: a permanent test-suite capability that exercises degraded-input scenarios (HA offline, missing prices, sensor spikes, DST, restart mid-slot) and asserts safe degradation.

### Modified Capabilities

<!-- none — the review diagnoses; fixes to existing capabilities become their own changes with their own delta specs -->

## Impact

- **Read-only**: production DB (`planner_learning.db` via `ssh darkstar`, `mode=ro`) and rotated logs; no production data is modified.
- **New code**: one backend monitors module (+ its API/alert surface) and new fault-injection tests under `tests/`. No behavior changes to planner, executor, ML, or recorder in this change.
- **Artifacts**: `findings.md` ledger inside this change directory; each S1/S2 finding is expected to spawn a follow-up fix change.
- **Conventions**: diagnose-only rule (app code untouched except the monitors module), findings numbered and severity-rated, fresh session per phase recommended (`design.md` documents the working rules).
