# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 58 — The Weather Strategist (Strategy Engine) *(Status: 📋 Planned)*

*   **Goal**: Transform the Strategy Engine from static rules to reactive logic. It must calculate forecast uncertainty (Volatility) and adjust `s_index` weights dynamically to increase safety margins during chaotic weather.
*   **Philosophy**: "When the forecast is unstable, trust the forecast less and the battery reserve more."

**Scope & Logic**

1.  **The Eyes (`ml/weather.py`)**:
    *   Extend the Open-Meteo fetcher to calculate a **Volatility Score** (0.0 to 1.0) for Cloud Cover and Temperature over the next 24 hours.
    *   *Math*: `Volatility = min(1.0, standard_deviation / normalization_factor)`.
    *   *Normalization*: For Cloud Cover (0-100%), a standard deviation of 40 is "Extreme Chaos".

2.  **The Wiring (`inputs.py`)**:
    *   Call the new weather metric function in `get_all_input_data`.
    *   Inject these metrics into the `context` dictionary (alongside `vacation_mode`).

3.  **The Brain (`backend/strategy/engine.py`)**:
    *   Implement a linear sliding scale to adjust `s_index` weights.
    *   **Cloud Volatility** → Increases `s_index.pv_deficit_weight`. (If sun is unreliable, panic more about deficits).
    *   **Temp Volatility** → Increases `s_index.temp_weight`. (If temp is swinging, panic more about cold).
    *   *Constraint*: Never decrease weights below the `config.yaml` base values (Safety First). Only scale up.

**Detailed Implementation Steps**

1.  **Update `ml/weather.py`**:
    *   Add function `get_weather_volatility(start_time, end_time, config) -> Dict[str, float]`.
    *   Fetch hourly `cloud_cover` and `temperature_2m` from Open-Meteo (using existing caching/logic if possible, or fresh fetch).
    *   Calculate `std_dev` for both series over the window.
    *   Return `{'cloud_volatility': float, 'temp_volatility': float}` (normalized 0.0-1.0).

2.  **Update `inputs.py`**:
    *   In `get_all_input_data`, define a 24h window (`now` to `now + 24h`).
    *   Call `get_weather_volatility`.
    *   Update the `context` dictionary construction:
        ```python
        context = {
            "vacation_mode": ...,
            "weather_volatility": volatility_result  # New field
        }
        ```

3.  **Update `backend/strategy/engine.py`**:
    *   In `decide(input_data)`, extract `context.weather_volatility`.
    *   Read base config weights: `base_pv_weight = self.config['s_index']['pv_deficit_weight']`.
    *   Apply Logic:
        ```python
        # Example Logic
        cloud_vol = context['weather_volatility']['cloud'] # 0.0 to 1.0
        # Max penalty: Add up to 0.4 to the weight
        pv_weight_adj = base_pv_weight + (cloud_vol * 0.4)
        overrides['s_index']['pv_deficit_weight'] = round(pv_weight_adj, 2)
        ```
    *   Log the adjustment logic using `logger.info` ("Weather Volatility is High (0.8). Increasing PV Weight to 0.9").

4.  **Verify (`debug/test_strategy_weather.py`)**:
    *   Create a standalone script in `debug/` that initializes `StrategyEngine` with a dummy config.
    *   Feed it a mock `input_data` with `context={'weather_volatility': {'cloud': 0.9}}`.
    *   Assert that the returned overrides contain an increased `pv_deficit_weight`.

**Acceptance Criteria**
*   `inputs.py` successfully fetches variance without blocking/crashing.
*   Strategy Engine produces a valid override dict when volatility is present.
*   Planner logs show "Strategy Engine active" with the modified weights during execution.
*   `config.yaml` remains the static baseline; logic ensures we never dip *below* baseline safety.


### Rev 59 — Intelligent Memory (Aurora Correction) *(Status: 📋 Planned)*

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

### Rev 60 — Cross-Day Responsibility (Charging Ahead for Tomorrow) *(Status: 📋 Planned)*

*   **Goal**: Ensure the planner charges proactively in tonight’s lower-price windows to cover **tomorrow’s** high-price deficits, even when the battery is already near its strategic target at “now”.
*   **Problem Statement**: With the current logic, `_pass_1_identify_windows` uses **current SoC vs. static target** to decide if dynamic cheap-window expansion is needed. When SoC is near target at `now_slot`, the deficit is ≈0, so no future slots are marked `is_cheap`, `windows` is empty in `_pass_4_allocate_cascading_responsibilities`, and tomorrow’s expensive gaps receive **zero responsibility**. The result is a flat `soc_target_percent = min_soc` tomorrow and no pre-charging tonight.

**Design & Logic**

1. **Future-Deficit-Aware Cheap Windows**
    *   Extend `_pass_1_identify_windows` so that if `deficit_kwh` (current vs target) is small but **simulated future SoC** (from `_pass_3_simulate_baseline_depletion`) drops significantly below the strategic target during tomorrow’s high-price periods, those future deficits contribute to an effective `future_deficit_kwh`.
    *   Use this `future_deficit_kwh` to drive dynamic window expansion:
        *   If `future_deficit_kwh > baseline_capacity_kwh` and there are no future `is_cheap=True` slots, expand the threshold based on **future price distribution only** (prices where `df.index >= now_slot`).
        *   Guarantee that at least some lower-priced future slots (tonight vs tomorrow peaks) become `is_cheap=True`, forming real cheap windows beyond “now”.

2. **Cheapest-Future-Window Responsibility**
    *   In `_pass_4_allocate_cascading_responsibilities`, when `windows` is empty but:
        *   Tomorrow’s day has a complete price curve, and
        *   Simulated SoC shows a drop towards `min_soc` while `import_price_sek_kwh` stays high,
        create a synthetic cheap window over the **cheapest available future slots** (e.g., a block tonight) and assign responsibility for tomorrow’s net deficits to that window.
    *   Responsibility should be based on:
        *   `gap_net_load_kwh` computed from `adjusted_load_kwh - adjusted_pv_kwh` over tomorrow’s high-price intervals.
        *   S-index factor (safety) on top of that, as today.

3. **SoC Targets Reflect Future Responsibility**
    *   Ensure `_apply_soc_target_percent` respects new “Charge” blocks assigned to cross-day responsibilities, raising `soc_target_percent` above `min_soc` for:
        *   Tonight’s charge blocks.
        *   Tomorrow’s protected intervals where we want to hold charge instead of resting at `min_soc`.

**Scope**
*   `planner.py`:
    *   `_pass_1_identify_windows`: incorporate future deficits (via `simulated_soc_kwh` or equivalent) into cheap-window expansion, and fallback to a **future-only** price percentile when no future cheap slots exist.
    *   `_pass_4_allocate_cascading_responsibilities`: add a fallback path when `windows` is empty but tomorrow’s prices and loads clearly imply a deficit, assigning responsibility to the cheapest future slots.
    *   `_apply_soc_target_percent`: verify that new Charge blocks and Hold logic produce non-flat SoC targets across the night/tomorrow boundary.

**Acceptance Criteria**
*   With a scenario like the current one (cheap tonight, very expensive tomorrow, battery near target at “now”):
    *   The planner produces **non-zero charging** in tonight’s lower-price slots.
    *   `soc_target_percent` for tomorrow is **above `min_soc`** over at least the expensive periods where we want to use the battery.
    *   `df["is_cheap"]` has `True` values for some future slots (after `now_slot`), and `_pass_4` generates `window_responsibilities` that cover tomorrow’s high-price deficits.
*   When future prices are flat or tomorrow is not actually expensive relative to tonight, behavior remains close to current (no over-charging purely for the sake of it).

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
