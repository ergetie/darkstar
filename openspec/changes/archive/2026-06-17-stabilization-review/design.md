## Context

Darkstar's decision core (`backend/`, `planner/`, `ml/`, `executor/`) is ~67k LOC of Python with a strong test suite (983 tests) but a weak CI floor (only the API subset runs), strict pyright that isn't enforced in CI, and two confirmed user-facing defects. Investigation has already localized both:

- **EV-from-PV (S1):** In the Kepler objective (`planner/solver/kepler.py:489–500`), `slot_ev_cost = 0.0`; EV charging is rewarded only via aggregate "incentive buckets" (`kepler.py:203–234, 642–651`). Charging from surplus PV forfeits `export_revenue`, and the bucket's per-kWh value falls below the export price once the EV isn't nearly empty — so the solver exports. With `penalty_levels: []` there is zero incentive. The root cause is structural: **free PV → EV has no intrinsic value in the objective.**
- **PV hybrid 2× (S2):** `final = physics_kwh + ml_residual` with no upper clamp and an unbounded additive residual (`ml/forward.py:328–352`; physics in `ml/weather.py`). The residual is trained as **absolute kWh** (`actual − physics`); the shipped seed model is non-transferable across array sizes, which explains why only *some* users are affected.

This review is **diagnose-only**. It writes documentation, runs in heavy per-phase sessions, and must survive being stopped and resumed. The governing principle: a finding that "reads as correct" (the EV bug) is only caught by **tracing behavior**, not by skimming files.

## Goals / Non-Goals

**Goals:**
- Find and document all bugs and architectural risks in the four core packages.
- Produce a single self-contained living ledger (`findings.md`) that any fresh session can pick up without conversation history.
- Make the effort resumable at **phase/domain** granularity.
- End each confirmed finding in a state ready to seed a downstream OpenSpec bug-fix change.

**Non-Goals:**
- **No application code, config, schema, or dependency changes.** Zero edits to `backend/`, `planner/`, `ml/`, `executor/`, or runtime files.
- No fixes — candidate remedies are *recorded*, not implemented.
- No frontend investigation (gaps may be noted as findings only).
- No solution/architecture decisions for the two anchor bugs — those happen in later sessions reading `findings.md`.

## Decisions

### D1 — `findings.md` is the single source of truth (append-only numbered ledger)
Each finding is one entry in a numbered list, never renumbered, never deleted (status changes to `wontfix` instead). It carries enough context to stand alone. **Why over per-phase docs:** fresh-session-per-phase means scattered state gets lost; one append-only file is the lowest-risk handoff. `design.md` (this file) holds the *rules*; `findings.md` holds the *data* and references back here.

**Finding format (fixed):**
```
### Finding #N — <short title>
- **Severity:** S1 | S2 | S3 | S4
- **Domain:** forecasting | solver-economics | executor | recorder-data | config-migration | infra-tests | architecture
- **Status:** open | confirmed | wontfix | → <child-change-name>
- **Location:** file:line (+ more)
- **Symptom:** what is observably wrong
- **Root-cause hypothesis:** mechanism (mark CONFIRMED vs UNVERIFIED)
- **Candidate remedies:** options only — NOT a commitment to implement
- **Phase / session:** where it was found
```

### D2 — Severity rubric (S1–S4)
| Sev | Meaning | Example |
|-----|---------|---------|
| **S1** | Wrong physical action / safety / direct money loss | EV exporting instead of charging |
| **S2** | Wrong decision input (bad forecast → bad plan) | PV 2× overestimate |
| **S3** | Correctness bug, bounded blast radius | unit slip in a display-only path |
| **S4** | Smell / debt / missing test / CI gap | god files, CI runs only API tests |

### D3 — Phased methodology, sequenced depth
- **Phase 0 — Baseline & Freeze:** run the full suite locally and record pass/fail; document the 3 stale `price-forecasting-module-*` changes as paused; record the CI gap; seed findings #1–#3; confirm `findings.md` + rubric are in place.
- **Phase 1 — Anchor spikes (diagnose only):** isolate the PV bug into Layer A (physics alone vs open-meteo) vs Layer B (residual transfer) using one affected user's config + a day's data; confirm the EV objective economics against a real config + prices. Output: documented root cause per bug. **Stops before any fix design.**
- **Phase 2a — Broad pass:** light read of every file in the four packages for obvious slips (dead code, silent `except`, unguarded math, kWh/kW/0.25h confusion, stale REV-comments vs behavior). Cheap to fan out across subagents.
- **Phase 2b — Deep behavior dives:** trace concrete scenarios through the risky domains — forecasting, solver economics, executor control, recorder/data-consistency, config migration. This is where "reads-correct-but-wrong" bugs surface.
- **Phase 3 — Architecture review:** the two-PV-estimator reconciliation question, god files (`executor/engine.py` 2035, `actions.py` 1244), async/threading + SQLite WAL contention, data-SSOT claims, and safety invariants (what protects battery/grid if a forecast is insane).

### D4 — Subagent contract
Every fan-out agent is read-only and returns findings in the D1 format: `file:line + symptom + why`, plus a confidence flag (CONFIRMED vs UNVERIFIED). Agents do **not** triage — the operator + user decide what is real (the EV bug demonstrates why a single-file read mislabels it "correct"). Agents never edit files.

### D5 — Fresh-session handoff discipline
A phase session, in order: (1) reads `design.md` then `findings.md`; (2) reads its phase block in `tasks.md`; (3) does only that phase, **read-only on app code**; (4) appends new findings to `findings.md`; (5) ticks the phase checkbox in `tasks.md`; (6) stops. Solution sessions come later and read `findings.md` to spin up (sometimes batched) bug-fix changes.

## Risks / Trade-offs

- **Risk:** A subagent flags a behavior bug as "correct code." → **Mitigation:** D4 mandates scenario tracing + a CONFIRMED/UNVERIFIED flag; operator triage is required before a finding is marked `confirmed`.
- **Risk:** State lost between heavy per-phase sessions. → **Mitigation:** D1 append-only ledger + D5 handoff checklist; `findings.md` is self-contained by rule.
- **Risk:** Scope creep into fixing during diagnosis. → **Mitigation:** hard non-goal (D-Goals); candidate remedies are recorded, never applied; this change touches no app code.
- **Risk:** Per-domain (not per-file) checkpointing loses fine-grained resume position. → **Trade-off accepted:** per the operator's preference; the findings ledger carries file-level detail so coverage is still traceable.
- **Risk:** Broad pass (2a) produces noise that buries S1/S2 issues. → **Mitigation:** sequenced — anchor spikes (Phase 1) run first; rubric forces severity tagging so S1/S2 stay visible.

## Open Questions

- Which PV estimator is "truth" and whether the hybrid needs a sanity clamp and/or a disable toggle — **deferred by design** to a post-review solution session (the operator has indicated the hybrid stays the driver, nothing is removed).
- Whether downstream fixes are batched or per-finding — decided per-finding in solution sessions, not here.

## References
- `proposal.md` — motivation and scope.
- `findings.md` — the living findings ledger (pre-seeded with findings #1–#3).
- `specs/stabilization-review/spec.md` — testable requirements for this review process.
