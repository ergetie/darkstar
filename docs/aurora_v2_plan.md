# AURORA v2: The AI Agent

**AURORA**: **A**daptive **U**sage & **R**enewables **O**ptimization & **R**esponse **A**nalyzer

## 1. Vision & Philosophy

Aurora v2 marks the transition of Darkstar from a **Smart Tool** to an **Intelligent Agent**.

Currently, Darkstar is a calculator. It takes static settings (`config.yaml`) and optimizes them.
Aurora v2 is a butler. It observes the home's context (Alarm, Vacation, Weather, Prices) and actively decides how the system should behave.

### The Architecture: The "Brain Implant"
We do not rewrite the deterministic Planner. Instead, we introduce a **Strategy Layer**.

**Flow:**
1.  **Context:** `StrategyEngine` gathers data (Vacation? Alarm? Weather? Prices?).
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

## 3. Implementation Status

#### Rev 18 — Strategy Injection Interface ✅ Completed
*   **Summary:** Refactored `planner.py` to accept runtime config overrides. Created `backend/strategy/engine.py`. Added `strategy_log` table.
*   **Validation:** `debug/test_overrides.py` confirmed planner respects injected `target_soc` and `price_thresholds`.

#### Rev 19 — Context Awareness ✅ Completed
*   **Summary:** Connected `StrategyEngine` to `inputs.py`. Implemented `VacationMode` rule (disable water heating).
*   **Fixes:** Rev 19.1 hotfix removed `alarm_armed` from water heating disable logic (occupants need hot water).
*   **Validation:** `debug/test_vacation.py` confirmed `water_heating.min_hours` drops to 0 when vacation mode is simulated.

#### Rev 20 — Smart Thresholds (Dynamic Window Expansion) ✅ Completed
*   **Summary:** Updated `_pass_1_identify_windows` in `planner.py`. Logic now calculates energy deficit vs window capacity and expands the "cheap" definition dynamically to meet `target_soc`.
*   **Validation:** `debug/test_smart_thresholds.py` simulated a massive 100kWh empty battery with a strict 5% price threshold. Planner successfully expanded the window from ~10 slots to 89 slots to meet demand.

#### Rev 21 — "The Lab" (Simulation Playground) ✅ Completed
*   **Summary:** Added `/api/simulate` support for overrides. Created `Lab.tsx` UI for "What If?" scenarios (Battery Size, Max Power).
*   **Files:** `backend/webapp.py`, `frontend/src/pages/Lab.tsx`.

### Rev 22 — The Weather Strategist (S-Index Weights)
*   **Goal:** AI manipulates S-Index *Weights* (not just the base factor) based on forecast uncertainty.
*   **Logic:**
    *   If `cloud_cover_variance` is high (uncertainty): Increase `pv_deficit_weight` (be paranoid about solar).
    *   If `temperature_variance` is high: Increase `temp_weight`.
*   **Scope:** `ml/weather.py` (new metric: variance), `backend/strategy/engine.py`.

### Rev 23 — The Market Strategist (Price Variance)
*   **Goal:** Adapt charging pickiness based on market volatility.
*   **Logic:**
    *   **Flat Prices:** Tighten `charge_threshold_percentile` (e.g., 10%). Don't cycle the battery for pennies.
    *   **Volatile Prices:** Relax `charge_threshold_percentile` (e.g., 20%). Grab all cheap power to arbitrage the peaks.
*   **Scope:** `backend/strategy/engine.py`.

### Rev 24 — The Storm Guard
*   **Goal:** Protect the home against grid outages during severe weather.
*   **Logic:**
    *   If `wind_speed > 20 m/s` OR `snowfall > X cm` (via Open-Meteo):
    *   Override `battery.min_soc_percent` to 30% (or user configurable safety floor).
*   **Scope:** `inputs.py` (fetch weather hazards), `backend/strategy/engine.py`.

### Rev 25 — The Analyst (Manual Load Optimizer)
*   **Goal:** Calculate the mathematically optimal time to run heavy appliances (Dishwasher, Dryer) over the next 48h.
*   **Scope:**
    *   New logic in `backend/strategy/analyst.py`.
    *   Scans price/PV forecast to find "Golden Windows" (lowest cost for 3h block).
    *   Outputs a JSON recommendation (e.g., `{"dishwasher": {"start": "14:00", "saving": "5 SEK"}}`).

### Rev 26 — The Voice (Smart Advisor)
*   **Goal:** Present the Analyst's findings via a friendly "Assistant" using an LLM.
*   **Scope:**
    *   `secrets.yaml`: OpenRouter API Key.
    *   `backend/llm_client.py`: Interface to OpenRouter (Google Gemini Flash 1.5 or similar).
    *   **UI:** A "Smart Advisor" card on the Dashboard.
    *   **Prompt:** "Current price is High. Best time is 14:00. Tell the user what to do in one friendly sentence."

---

## 5. Backlog (Tactical Fixes)
*   [ ] **Manual Plan Simulate:** Verify if manual block additions in Planning Tab still work correctly with the new `simulate` signature (regression testing).

---

## 6. Future Ideas (Darkstar 2.0)
*Strategic features out of scope for current Aurora v2 cycle.*
*   **Grid Peak Shaving (Effekttariff):** Detect predicted monthly peaks and force-discharge battery to cap grid import. (Planned for next year).
*   **Smart EV Integration:** Prioritize home battery vs. EV charging based on "Departure Time".
*   **Tariff Hopper:** Cost analyzer for different energy contracts (Hourly vs Monthly).
*   **Solar Config UI:** Move hardware settings (Azimuth/Tilt/KwP) from YAML to UI.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.