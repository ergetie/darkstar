## Context

These eight findings came out of the stabilization review as confirmed, low-severity (S3/S4), independent defects with bounded blast radius and no architecture decision attached. They are deliberately batched into one cleanup change so the higher-severity changes (`recorder-ssot`, `harden-executor-safety`, `config-migration-hardening`, `fix-ml-forecast-correctness`) stay focused, and so the same files are not reopened in many tiny PRs. Findings #34/#35/#22/#23 live in `harden-executor-safety`; #36 (god-file refactor) is a separate, later change — none of those are touched here.

## Goals / Non-Goals

**Goals:**
- Land all eight fixes with no behavior change beyond each finding's stated correction.
- Keep each fix independently revertable (one task group per finding).
- Correct, not paper over: remove the dead `force_export` path rather than fix an unreachable branch.

**Non-Goals:**
- No architecture decisions (those are the other changes' Open Questions).
- No execution-time safety clamp, no recorder/SSOT work, no ML pipeline work.
- No refactor of `engine.py`/`actions.py` structure (#36 is its own change).

## Decisions

- **#8 — nominal not min voltage.** Use `nominal_voltage_v` in the kW→A conversion; keep `min_voltage_v` for safety limits only. *Alternative considered:* document worst-case voltage as intentional — rejected, the direction is a consistent ~4% overshoot, not a deliberate margin.
- **#21 — remove, don't fix.** `force_export` has no UI caller and writes a 0 W export limit. Remove the override type, controller branch, and engine handler. *Alternative:* fix the 0 W bug — rejected as dead code with no consumer; only revisit if a force-export button is ever added.
- **#20 — report-only.** Align the cost recompute to the effective (thresholded) export price the objective used. The solver is already internally consistent; only the displayed number changes. No schedule changes.
- **#12 + #14 (simulation) — treat together.** Both concern `planner/simulation.py`'s SoC projection: feed it total battery charge (not the grid-only `charge_kw`) and apply the parsed-but-discarded min/max SoC clamp. This only affects the `/api/simulate` diagnostic endpoint (the live plan uses Kepler's true SoC state), so it is display-path correctness.
- **#19, #14 (non-simulation) — comments/dead-code only, no spec.** Repair the stale Kepler terminal-value comments + duplicate `target_soc_kwh` assignment, and delete the discarded reads / unreachable `if entity is None` branch / redundant `pass`. No observable behavior change, so these are tasks with no spec requirement.
- **#13, #24 — observability/delivery.** Log WS broadcast failures instead of swallowing; `await` the boost-cancellation notification. Match the existing logged/awaited call sites already in the same files.

## Risks / Trade-offs

- **Shared `executor` spec with `harden-executor-safety`** → requirements are disjoint (this change: EV current, notification delivery, WS logging, force_export removal; that change: manual override, EV override gating, stale-schedule hold). Deltas merge cleanly at archive; verified no requirement-name overlap.
- **Shared `kepler.py` edits (#19/#20) with `#34` and paused `price-forecasting-module-3/4`** → land this cleanup first or coordinate, so the comment/cost edits don't collide with later objective/S-Index work on the same lines.
- **#12 changes a diagnostic endpoint's output** → low risk (no live planning consumer), but any test asserting the old grid-only SoC curve must be updated.
- **Removing `force_export` (#21)** → if a raw-API integration relies on it, it breaks; judged acceptable since it currently exports nothing (0 W) and has no documented consumer.

## Migration Plan

No data, schema, or config migration. Each finding is its own task group; revert is per-group. `force_export` removal is the only deletion — no user-facing surface is lost (no UI button exists).
