# Darkstar Energy Manager: Active Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Revision Naming Conventions

| Prefix | Area | Examples |
|--------|------|----------|
| **K** | Kepler (MILP solver) | K1-K19 |
| **E** | Executor | E1 |
| **A** | Aurora (ML) | A25-A29 |
| **H** | History/DB | H1 |
| **O** | Onboarding | O1 |
| **UI** | User Interface | UI1, UI2 |
| **DS** | Design System | DS1 |
| **F** | Fixes/Bugfixes | F1-F6 |
| **DX** | Developer Experience | DX1 |
| **ARC** | Architecture | ARC1-ARC* |

---

## 🤖 AI Instructions (Read First)

1.  **Structure:** This file is a **chronological stream**. Newest items are at the **bottom**.
    
2.  **No Reordering:** Never move items. Only update their status or append new items.
    
3.  **Status Protocol:**
    
    -   Update the status tag in the Header: `### [STATUS] REV // ID00 — Title`
        
    -   Allowed Statuses: `[DRAFT]`, `[PLANNED]`, `[IN PROGRESS]`, `[DONE]`, `[PAUSED]`, `[OBSOLETE]`.
        
4.  **New Revisions:** Always use the template below.
    
5.  **Cleanup:** When this file gets too long (>15 completed items), move the oldest `[DONE]` items to `CHANGELOG.md`.
    

### Revision Template

```

### [STATUS] Rev ID — Title

**Goal:** Short description of the objective.
**Plan:**

#### Phase 1: [STATUS]
* [ ] Step 1
* [ ] Step 2

#### Phase 2: [STATUS]
* [ ] Step 1
* [ ] Step 2

```

---

## REVISION STREAM:

---

### [PLANNED] REV // PERF1 — MILP Solver Performance Optimization

**Goal:** Reduce Kepler MILP solver execution time from 22s to <5s by optimizing or eliminating the water heating spacing constraint.

**Context:** Profiling revealed that the planner spends 22 seconds in the Kepler MILP solver, primarily due to the water heating "spacing penalty" constraint (lines 282-287 in `planner/solver/kepler.py`). This constraint creates O(T × spacing_slots) ≈ 2000 pairwise constraints for a 100-slot horizon with a 5-hour spacing window. Disabling the spacing penalty (`water_spacing_penalty_sek: 0`) reduces solver time to 9.79s, proving it's the bottleneck.

**Profiling Results:**
- **With spacing penalty**: 22s solver time
- **Without spacing penalty**: 9.79s solver time
- **Improvement**: 55% faster (12s saved)

**Priority:** **HIGH** — This directly impacts user experience (planner runs every 30 minutes).

#### Phase 1: Investigation [PLANNED]
**Goal:** Understand the trade-offs and identify optimization strategies.

* [ ] **Document Current Behavior:**
  - What is the spacing penalty supposed to prevent? (Frequent water heater on/off cycles for efficiency)
  - What happens if we disable it? (More frequent heating blocks, potential efficiency loss)
  - Quantify comfort/efficiency impact: Run 1 week simulation with/without spacing penalty

* [ ] **Analyze Constraint Complexity:**
  - Current: O(T × spacing_slots) where T=100, spacing_slots=20 → 2000 constraints
  - Why is this slow? (Branch-and-bound in MILP solver scales poorly with binary variable pairwise constraints)

* [ ] **Research Alternative Formulations:**
  - **Option A:** Aggregate constraint (e.g., "max 3 heating blocks per day" instead of pairwise spacing)
  - **Option B:** Lookahead constraint (only check past N slots, not all slots in window)
  - **Option C:** Soft heuristic post-solve (run MILP without spacing, then penalize solutions with violations)
  - **Option D:** Completely remove spacing, rely only on gap penalty for comfort

* [ ] **Benchmark Alternatives:**
  - Implement Option A/B/C in separate branches
  - Measure solver time and solution quality
  - Document results in comparison table

#### Phase 2: Implementation [PLANNED]
**Goal:** Deploy the best-performing alternative from Phase 1.

* [ ] **Code Changes:**
  - Modify `planner/solver/kepler.py` to implement chosen alternative
  - Update `planner/solver/adapter.py` if config mapping changes
  - Add config option to toggle old/new behavior (for A/B testing)

* [ ] **Testing:**
  - Unit tests for new constraint logic
  - Integration test: Verify planner runs in <10s
  - Regression test: Compare schedules before/after (should be similar quality)

#### Phase 3: Validation [PLANNED]
**Goal:** Verify production-readiness.

* [ ] **Performance Verification:**
  - Run `scripts/profile_deep.py` → Planner should be <10s
  - Stress test: 1000-slot horizon (edge case) should still solve in reasonable time

* [ ] **Quality Verification:**
  - Manual inspection: Do water heating blocks look reasonable?
  - Energy efficiency: Compare total kWh heating cost before/after

* [ ] **Documentation:**
  - Update `planner/solver/kepler.py` docstrings
  - Add performance notes to `docs/ARCHITECTURE.md`

**Exit Criteria:**
- [ ] Planner execution time reduced from 22s to <10s
- [ ] Water heating schedule quality remains acceptable (user-verified)
- [ ] All tests pass
- [ ] Changes documented

---

### REV // F13 — Socket.IO Debug Cleanup [POST-BETA]

**Goal:** Remove verbose debug logging and runtime config after beta testers have confirmed stable Socket.IO connections across various environments.

**Context:** REV F11 added extensive instrumentation to debug the HA Ingress connection issue:
- `console.log` statements throughout `socket.ts`
- `?socket_path` and `?socket_transports` URL param overrides
- Packet-level logging (`packetCreate`, `packet` events)

This should remain in place during beta testing to allow users to self-diagnose issues.

**Cleanup Scope:**
- [ ] Remove or reduce `console.log` statements in `socket.ts`
- [ ] Consider keeping URL param overrides as a hidden "power user" feature
- [ ] Remove `eslint-disable` comments added for debug casting
- [ ] Update `docs/ARCHITECTURE.md` if runtime config is removed

**Trigger:** After 2+ weeks of stable beta feedback with no new Socket.IO issues reported.

**Priority:** Low (cleanup only, no functional change)

---
