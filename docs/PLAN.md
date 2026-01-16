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

### [DONE] REV // H2 — Training Episodes Database Optimization

**Goal:** Reduce `training_episodes` table size.

**Outcome:**
Instead of complex compression, we decided to **disable writing to `training_episodes` by default** (see `backend/learning/engine.py`). The table was causing bloat (2GB+) and wasn't critical for daily operations.

**Resolution:**
1.  **Disabled by Default:** `log_training_episode()` now checks `debug.enable_training_episodes` (default: False).
2.  **Cleanup Script:** Created `scripts/optimize_db.py` to trim/vacuum the database.
3.  **Documentation:** Added `optimize_db.py` usage to `docs/DEVELOPER.md`.

**Status:** [DONE] (Solved via Avoidance)

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

### REV // F12 — Scheduler Not Running First Cycle [TO INVESTIGATE]

**Problem:** Scheduler shows `last_run_at: null` even though enabled and running.
From debug endpoint:
```json
{
  "status": "running",
  "enabled": true,
  "runtime": {
    "last_run_at": null,
    "next_run_at": "2026-01-15T09:15:27",
    "last_run_status": null
  },
  "diagnostics": {
    "message": "🔄 Scheduler is enabled but hasn't run yet (waiting for first scheduled time)"
  }
}
```

**To Investigate:**
- [ ] Why scheduler waits until next boundary instead of running immediately on startup
- [ ] Check if `next_run_at` calculation is correct
- [ ] Consider adding "run immediately on startup if enabled" behavior

**Priority:** Medium (scheduler works, just delayed start)

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

### [PLANNED] REV // F15 — Extend Conditional Visibility to Parameters Tab

**Goal:** Apply the same `showIf` conditional visibility pattern from F14 to the Parameters/Settings tabs (not just HA Entities).

**Context:** The System Profile toggles (`has_solar`, `has_battery`, `has_water_heater`) should control visibility of many settings across all tabs:
- Water Heating parameters (min_kwh, spacing, temps) — grey if `!has_water_heater`
- Battery Economics — grey if `!has_battery`
- S-Index settings — grey if `!has_battery`
- Solar array params — grey if `!has_solar`
- Future: EV Charger, Heat Pump, Pool Heater, multiple MPPT strings

**Scope:**
- Extend `showIf` to `parameterSections` in `types.ts`
- Apply same greyed overlay pattern in ParametersTab
- Support all System Profile toggles as conditions

**Priority:** Low (foundation is set in F14, this is expansion)

**Dependencies:** REV F14 must be complete first

---

### [DONE] REV // UI5 — Support Dual Grid Power Sensors

**Goal:** Support split import/export grid power sensors in addition to single net-metering sensors.

**Plan:**

#### Phase 1: Implementation [PLANNED]
* [X] Add `grid_import_power_entity` and `grid_export_power_entity` to config/Settings
* [X] Update `inputs.py` to handle both single (net) and dual sensors
* [X] Verify power flow calculations

---

### [DONE] REV // E3 — Inverter Compatibility (Watt Control)

**Goal:** Support inverters that require Watt-based control instead of Amperes (e.g., Fronius).

**Outcome:**
Implemented strict separation between Ampere and Watt control modes. Added explicit configuration for Watt limits and entities. The system now refuses to start if Watt mode is selected but Watt entities are missing.

**Plan:**

#### Phase 1: Implementation [DONE]
* [x] Add `control_unit` (Amperes vs Watts) to Inverter config
* [x] Update `Executor` logic to calculate values based on selected unit
* [x] Verify safety limits in both modes

---

### [DONE] REV // E4 — Config Flexibility & Export Control

**Goal:** Improve configuration flexibility by making the SoC target entity optional (increasing compatibility with inverters that manage this internally) and implementing a strict export toggle associated with comprehensive UI conditional visibility.

**Plan:**

#### Phase 1: Optional SoC Target [DONE]
**Goal:** Make `soc_target` entity optional for inverters that do not support it, while clarifying its behavior for those that do.
* [x] **Config Update:** Modify `ExecutorConfig` validation to allow `soc_target_entity` to be None/empty.
* [x] **Executor Logic:** Update `executor/engine.py` to gracefully skip `_set_soc_target` actions if the entity is not configured.
* [x] **UI Update (Tooltip):** Update `soc_target_entity` tooltip: "Target maintenance level. Acts as a discharge floor (won't discharge below this %) AND a grid charge target (won't charge above this % from grid). Required for inverters like Deye (behavior for other inverters unknown)."
* [x] **UI Update (Optionality):** Field should be marked optional in the form validation logic.

#### Phase 2: Export Toggle & UI Logic [DONE]
**Goal:** Allow users to disable grid export constraints and hide irrelevant settings in the UI.
* [x] **Config:** Ensure `config.default.yaml` has `export.enable_export: true` by default.
* [x] **Constraint Logic:** In `planner/solver/kepler.py`, read `export.enable_export`. Add global constraint: `export_power[t] == 0` if disabled.
* [x] **UI Toggle:** Remove `disabled` and `notImplemented` flags from `export.enable_export` in `types.ts`.
* [x] **UI Conditionals:** Apply `showIf: { configKey: 'export.enable_export' }` to:
  *   `executor.inverter.grid_max_export_power_entity`
  *   `input_sensors.grid_export_power` (and related total/today export sensors)
  *   Any export-specific parameters in `Settings/Parameters`.
* [x] **Frontend Update:** Ensure `types.ts` defines these dependencies correctly so they grey out/disable.

#### Phase 3: Verification [DONE]
**Goal:** Verify safety, correctness, and UI behavior.
* [x] **Startup Test:** Verify Darkstar starts correctly with `soc_target_entity` removed.
* [x] **Planner Test:** Run planner with `enable_export: false` → verify 0 export.
* [x] **UI Test:** Toggle `enable_export` in System Profile/Config and verify export fields grey out.
* [x] **Regression Test:** Verify normal operation with `enable_export: true`.

---

### [DONE] REV // E5 — Inverter Profile Foundation

**Goal:** Establish a modular "Inverter Profile" system in the settings UI. This moves away from generic toggles towards brand-specific presets, starting with hiding `soc_target_entity` for non-Deye inverters.

**Profiles:**
1.  **Generic (Default):** Standard entities, `soc_target` hidden.
2.  **Deye/SunSynk (Gen2 Hybrid):** `soc_target` enabled & required.
3.  **Fronius:** Placeholder (same as Generic for now).
4.  **Victron:** Placeholder (same as Generic for now).

**Plan:**

#### Phase 1: Configuration & UI Schema [DONE]
* [x] **Config:** Add `system.inverter_profile` to `config.default.yaml` (default: "generic").
* [x] **UI Schema:**
    *   Add `system.inverter_profile` dropdown to System Profile card.
    *   Update `executor.soc_target_entity` to `showIf: { configKey: 'system.inverter_profile', value: 'deye' }` (or similar ID).
* [x] **Warning Label:** Add a UI hint/warning that non-Deye profiles are "Work in Progress".

#### Phase 2: Executor Handling [DONE]
* [x] **Executor Logic:** Ensure `executor/config.py` loads the profile key (for future logic branching).
* [x] **Validation:** Ensure `soc_target_entity` is only required if profile == Deye.

#### Phase 3: Verification [DONE]
* [x] **UI Test:** Select "Generic" → `soc_target` disappears. Select "Gen2 Hybrid" → `soc_target` appears.
* [x] **Config Persistency:** Verify `inverter_profile` saves to `config.yaml`.

---

### [DONE] REV // F16 — Conditional Configuration Validation

**Goal:** Fix the bug where disabling `has_battery` still requires `input_sensors.battery_soc` to be configured. Relax validation logic in both frontend and backend.

**Plan:**

#### Phase 1: Implementation [DONE]
* [x] **Frontend:** Update `types.ts` to add `showIf` to battery and solar fields.
* [x] **Backend:** Update `config.py` to condition critical entity validation on system toggles.
* [x] **Verification:** Verify saving config with `has_battery: false` works.

