# AURORA v2: The AI Agent

**AURORA**: **A**daptive **U**sage & **R**enewables **O**ptimization & **R**esponse **A**nalyzer

## 1. Vision & Philosophy

Aurora v2 marks the transition of Darkstar from a **Smart Tool** to an **Intelligent Agent**.

Currently, Darkstar is a calculator. It takes static settings (`config.yaml`) and optimizes them.
Aurora v2 is a butler. It observes the home's context (Alarm, Vacation, Weather, Prices) and actively decides how the system should behave.

### The Architecture: The "Brain Implant"
We do not rewrite the deterministic Planner. Instead, we introduce a **Strategy Layer**.

**Flow:**
1.  **Context:** `StrategyEngine` gathers data (Vacation? Alarm? Weather?).
2.  **Decision:** `StrategyEngine` generates a "Dynamic Config" (Overrides).
3.  **History:** The decision is logged to SQLite (`strategy_log`) for audit/debugging.
4.  **Execution:** `Planner` runs using `config.yaml` + `Overrides`.

---

## 2. Revision Template
*Use this template for every revision to ensure quality.*

### Rev [X] — [Title]
*   **Goal**: [What are we achieving?]
*   **Scope**: [Specific files/functions to touch]
*   **Verification Plan**:
    *   [ ] **Automated**: [Unit test or script name]
    *   [ ] **Manual**: [What to click/check in UI]
    *   [ ] **Data Check**: [What to verify in DB/JSON]

---

## 3. Implementation Plan

### Rev 18 — Strategy Injection Interface
*   **Goal:** Refactor `planner.py` to accept a runtime dictionary that overrides `config.yaml` values, and log these overrides to SQLite.
*   **Scope:**
    *   `planner.py`: Update `generate_schedule` to accept `overrides`.
    *   `backend/strategy/engine.py`: Create the base class.
    *   `backend/webapp.py`: Wire the engine to the planner call.
*   **Verification Plan:**
    *   [ ] **Script**: Create `debug/test_overrides.py` that forces a dummy override (e.g., `min_soc=99%`) and asserts the output `schedule.json` reflects it.

### Rev 19 — Context Awareness (The "Vacation" Fix)
*   **Goal:** Connect Strategy Engine to inputs to handle Vacation/Alarm states.
*   **Scope:**
    *   `inputs.py`: Fetch `vacation_mode` / `alarm_state`.
    *   `backend/strategy/rules.py`: Implement `VacationRule`.
    *   `planner.py`: Ensure water heating logic respects the override (0 hours).
*   **Verification Plan:**
    *   [ ] **Manual**: Toggle Vacation Mode in HA (or mock it), run planner, verify Water Heating is 0 in `schedule.json`.

### Rev 20 — Smart Thresholds (Dynamic Window Expansion)
*   **Goal:** Expand charging windows if the "Cheap" window is too short to reach `target_soc`.
*   **Scope:**
    *   `planner.py`: Refactor `_pass_1_identify_windows`.
    *   Calculate `Required Energy` vs `Window Capacity`.
    *   Relax `cheap_threshold` if `Deficit > 0`.
*   **Verification Plan:**
    *   [ ] **Data Check**: Run with a short cheap window (mocked prices). Verify planner schedules charging in "slightly expensive" slots to hit 100% SoC.

### Rev 21 — "The Lab" (Simulation Playground)
*   **Goal:** Add a UI view for "What If?" scenarios.
*   **Scope:**
    *   `frontend/src/pages/Lab.tsx`: UI for overriding config.
    *   `backend/webapp.py`: Ensure `/api/simulate` accepts overrides (done in Rev 18).
*   **Verification Plan:**
    *   [ ] **Manual**: Use The Lab to change Battery Size to 50kWh, run Sim, check the graph updates.

---

## 4. Backlog (Tactical Fixes)
*Items discovered during development that need fixing but aren't strategic features.*
*   [ ] (None yet)

---

## 5. Future Ideas (Darkstar 2.0)
*Strategic features out of scope for Aurora v2.*
*   **Grid Peak Shaving (Effekttariff):** Detect predicted monthly peaks and force-discharge.
*   **Smart EV Integration:** Prioritize home battery vs. EV charging.
*   **Tariff Hopper:** Cost analyzer for different energy contracts.
*   **Force Retrain Button:** UI control to clear learning cache.
*   **Solar Config UI:** Move hardware settings to UI.