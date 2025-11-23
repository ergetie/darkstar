# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 59 — Intelligent Memory (Aurora Correction) *(Status: ✅ Completed)*

*   **Goal**: Upgrade the Learning Engine from a static statistical average to an ML-based **Aurora Correction** model. This model predicts the *error* of the base forecast based on context (weather, time), allowing Darkstar to adapt to changing conditions immediately rather than waiting for a "bad day" to drag down the average.
*   **Philosophy**: "Aurora Forecast predicts the world. Aurora Correction predicts Aurora's blind spots."

**Architecture & Logic**

1.  **The Two-Model Approach**:
    *   **Model 1 (Aurora Forecast)**: Existing. Predicts raw Load/PV. (Stable).
    *   **Model 2 (Aurora Correction)**: New. Predicts `(Actual - Forecast)`. (Reactive).
2.  **The Graduation Path (Safety)**:
    *   **Level 0 (The Infant, <4 days data)**: Zero corrections. Trust base config.
    *   **Level 1 (The Statistician, 4-14 days)**: Rolling Average (Day-of-week/Hour bias).
    *   **Level 2 (The Graduate, 14+ days)**: LightGBM Error Model. Falls back to Level 1 if model confidence is low or output is extreme.
3.  **Persistence**:
    *   Corrections are stored per-slot in SQLite to ensure full observability of *why* a plan changed.

**Scope & Implementation Steps**

1.  **Database Schema Extension (`learning.py`)**:
    *   Update `_init_schema` to add columns to `slot_forecasts`:
        *   `pv_correction_kwh` (REAL)
        *   `load_correction_kwh` (REAL)
        *   `correction_source` (TEXT: 'ml', 'stats', 'none')
    *   *Migration*: Ensure existing rows get defaults (`0.0`, `'none'`).

2.  **The Corrector Engine (`ml/corrector.py`)**:
    *   **Training Logic**:
        *   Fetch historical `slot_forecasts` joined with `slot_observations`.
        *   Calculate residuals: `target = actual - base_forecast`.
        *   Train `ml/models/load_error.lgb` and `pv_error.lgb` using features: `temp`, `cloud`, `hour`, `day_of_week`, `vacation_mode`.
    *   **Inference Logic (`predict_corrections`)**:
        *   Check data depth (Graduation Path).
        *   If Level 2 (ML): Run inference. **Clamp** result to safe bounds (e.g., max +/- 50% of base).
        *   If Level 1 (Stats): Calculate rolling average for the specific hour/day.
        *   Return: `correction_vector`, `source_tag`.

3.  **The Pipeline Coordinator (`ml/pipeline.py`)**:
    *   Create a new entry point `run_inference(horizon_hours)` that orchestrates the flow:
        1.  **Forecast**: Call `ml.forward` (Model 1) → Base Forecasts.
        2.  **Correct**: Call `ml.corrector` (Model 2) → Adjustments.
        3.  **Persist**: Save Base + Correction + Source to `slot_forecasts`.

4.  **Wiring (`inputs.py`)**:
    *   Modify `get_all_input_data` to call `ml.pipeline.run_inference()`.
    *   Update `get_forecast_data` to read the *final* values (`base + correction`) from SQLite.
    *   *Crucial*: The Planner remains deterministic; it just receives the corrected numbers.

5.  **Automation (`learning.py`)**:
    *   Update `NightlyOrchestrator` to trigger `ml.corrector.train()` every night, keeping the "Junior" model fresh with the latest errors.

**Acceptance Criteria**
*   `slot_forecasts` table has populated correction columns.
*   Planner logs indicate the source of correction ("Applying ML Correction" vs "Applying Stats Fallback").
*   Simulating a context change (e.g., cold snap) results in an immediate forecast adjustment *before* the event occurs.

### Rev XX - PUT THE NEXT REVISION ABOVE THIS LINE!

---

## Backlog

### 🧠 Strategy & Aurora (AI)
*   **[Rev A25] Manual Plan Simulate Regression**: Verify if manual block additions in the Planning Tab still work correctly with the new `simulate` signature (Strategy engine injection).
*   **[Rev A27] Scheduled Retraining**: Automate `ml/train.py` execution (e.g., weekly) to keep Aurora models fresh without manual intervention. Similar to Rev 57!
*   **[Rev A28] The Analyst (Expansion)**: Add "Grid Peak Shaving" capability—detect monthly peaks and force-discharge battery to cap grid import fees.
*   **[Rev A29] Smart EV Integration**: Prioritize home battery vs. EV charging based on "Departure Time" (requires new inputs).

### 🖥️ UI & Dashboard
*   **[UI] Reset Learning**: Add "Reset Learning for Today" button to Settings/Debug to clear cached S-index/metrics without using CLI.
*   **[UI] Chart Polish**:
    *   Render `soc_target` as a step-line series.
    *   Add zoom support (wheel/controls).
    *   Offset tooltips to avoid covering data points.
    *   Ensure price series includes full 24h history even if schedule is partial.
*   **[UI] Mobile**: Improve mobile responsiveness for Planning Timeline and Settings.

### ⚙️ Planner & Core
*   **[Core] Dynamic Window Expansion (Smart Thresholds)**: *Note: Rev 20 in Aurora v2 Plan claimed this was done, but validating if fully merged/tested.* Logic: Allow charging in "expensive" slots if the "cheap" window is physically too short to reach Target SoC.
*   **[Core] Sensor Unification**: Refactor `inputs.py` / `learning.py` to read *all* sensor IDs from `config.yaml` (`input_sensors`), removing the need for `secrets.yaml` to hold entity IDs.

### 🛠️ Ops & Infrastructure
*   **[Ops] Deployment**: Document/Script the transfer of `planner_learning.db` and models to production servers.
*   **[Ops] Error Handling**: Audit all API calls for graceful failure states (no infinite spinners).

---

## Future Ideas (Darkstar 3.x+?)
*   **Multi-Model Aurora**: Separate ML models for Season or Weekday/Weekend.
*   **Admin Tools:** Force Retrain button, Clear Learning Cache button.
