## Why

Darkstar is being frozen for new features to stabilize. Two user-reported defects already point to systemic risk in the decision core: (1) PV forecasting overestimates badly for some users (open-meteo expected ~30 kWh, the hybrid estimated ~67 kWh), and (2) the EV exports surplus PV instead of charging from it. We need a structured, resumable review of `backend/`, `planner/`, `ml/`, and `executor/` that **finds and documents** all such bugs and architectural risks before any fixes are scoped — so fixes can be planned deliberately in later sessions rather than reactively.

## What Changes

This change introduces a **diagnose-only review process**. It produces documentation, not code.

- **NEW: `findings.md`** — a living, append-only numbered ledger. Every confirmed bug, smell, or risk is recorded as a numbered finding carrying its own severity, `file:line`, symptom, and root-cause hypothesis. It is self-contained so each phase can run in a fresh session without relying on conversation history.
- **NEW: severity rubric (S1–S4)** and a fixed finding format, defined in `design.md` and applied consistently across all phases.
- **NEW: phased, resumable methodology** — Phase 0 (baseline & freeze) → Phase 1 (anchor-bug spikes) → Phase 2a (broad sweep) → Phase 2b (deep behavior dives) → Phase 3 (architecture review). Checkpointing is **per-phase/per-domain**, not per-file.
- **Pre-seeded findings**: the two known bugs and the CI gap are recorded as findings #1–#3 at creation.
- **Explicit non-goal — NO application code changes.** This change never edits `backend/`, `planner/`, `ml/`, `executor/`, or any runtime file. Candidate remedies (e.g. a hybrid-disable toggle, a PV sanity clamp) are *recorded* in findings, not implemented. Each confirmed finding seeds a separate OpenSpec bug-fix change later (some batched).

## Capabilities

### New Capabilities
- `stabilization-review`: A documented, resumable diagnostic review process for the Darkstar decision core. Defines what findings must capture, the severity rubric, the diagnose-only boundary, the per-phase resumability contract, and the handoff discipline between fresh sessions.

### Modified Capabilities
<!-- None. This change makes no spec-level behavior changes to existing capabilities; it only diagnoses them. -->

## Impact

- **Scope (read-only):** `backend/`, `planner/`, `ml/`, `executor/`. Frontend is out of scope (smoke-test gaps may be noted as findings but not investigated).
- **Artifacts produced:** `proposal.md`, `design.md` (methodology), `findings.md` (living ledger), `tasks.md` (phase checkpoints).
- **No code, config, dependency, or schema changes.** No runtime behavior is affected.
- **Downstream:** confirmed findings become separate OpenSpec bug-fix changes in later sessions. Anchors already identified: PV hybrid overestimate (relates to `physics-based-pv-forecasting`, `open-meteo-pv-forecast`, `recency-weighted-training`) and EV-from-PV economics (relates to `per-device-ev-scheduling`, `excess-pv-planner-dispatch`).
- **Process side effect:** the 3 stale in-progress `price-forecasting-module-*` changes are documented as paused in Phase 0.
