# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

(Antares revisions archived to CHANGELOG.md)

### Rev K2 — Kepler Promotion (Primary Planner)

**Goal:** Promote Kepler to be the primary planner, generating the official `schedule.json` used for device control.

**Scope / Design Decisions:**
*   **Config Switch:** Introduce `config.kepler.primary_planner` (bool) to toggle between Heuristic and Kepler.
*   **Planner Refactor:** Modify `planner.py` to delegate the main scheduling logic to `KeplerSolver` when enabled.
*   **UI Compatibility:** Ensure the generated schedule DataFrame has all columns expected by the frontend (e.g., `battery_charge_kw`, `projected_soc_percent`).

**Implementation Steps:**
1.  **Planner Delegation:**
    *   Modify `HeliosPlanner.generate_schedule` to check `config.kepler.primary_planner`.
    *   If true, call `run_kepler_primary` (new method) and return its result.
    *   `run_kepler_primary` should call `KeplerSolver`, then convert the result back to the standard DataFrame format using `adapter.py`.
2.  **Config Update:**
    *   Update `config.yaml` to include `kepler: { enabled: true, shadow_mode: true, primary_planner: false }` (initially false).
3.  **Verification:**
    *   **Dry Run:** Run with `primary_planner: true` locally and inspect `schedule.json`.
    *   **UI Check:** Verify the dashboard renders the Kepler schedule correctly.
    *   **Production Rollout:** Enable on the live system and monitor for 24h.

**Status:** Completed.

### Rev K3 — Strategic S-Index (Decoupled Strategy)

**Goal:** Implement a robust risk management strategy that balances intra-day safety with inter-day optimization.

**Scope:**
*   **Decoupled Strategy:**
    *   **Load Inflation:** Static `base_factor` (e.g., 1.1x) for D1 forecast error safety.
    *   **Target SoC:** Dynamic Hard Constraint based on D2/D3 risk (Temperature/PV).
*   **Dynamic Target SoC:** `Target % = Min % + (Risk - 1.0) * Scaling`.
*   **UI:** Display S-Index and Target SoC on dashboard.

**Status:** Completed.

### Rev K4 — Kepler Vision & Benchmarking

**Goal:** Further refine Kepler and benchmark its performance against legacy MCP.

**Scope:**
*   **Benchmarking:** Compare MCP vs Kepler plans for Today and Tomorrow.
*   **Kepler Vision:** Implement features from `KEPLER_VISION.md`.
*   **Refinement:** Tune S-Index parameters based on real-world data.

**Status:** Completed.

### Rev K5 — Strategy Engine Expansion (The Tuner)

**Goal:** Empower the Strategy Engine to dynamically tune all key Kepler parameters (`wear_cost`, `ramping_cost`, `export_threshold`) based on context.

**Scope:**
*   **Kepler Solver:** Expose `wear_cost`, `ramping_cost`, `export_threshold` as runtime arguments in `solve()`.
*   **Strategy Engine:** Implement logic to override these parameters based on context (e.g., Price Volatility, Grid Constraints).
*   **Integration:** Ensure `planner.py` -> `adapter.py` -> `KeplerSolver` pipeline passes these overrides correctly.

**Implementation Steps:**
1.  **Solver Update:** Modify `KeplerSolver` to accept and use parameter overrides.
2.  **Strategy Logic:** Add new rules to `StrategyEngine` (e.g., "High Price Spread -> Lower Export Threshold").
3.  **Wiring:** Update `adapter.py` to map strategy output to solver inputs.
4.  **Verification:** Verify that changing context (e.g., via mock) alters the solver's internal parameters and resulting schedule.

**Status:** Completed.

### Rev K6 — The Learning Engine (Metrics & Feedback)

**Goal:** Close the loop by measuring "Plan vs Actual" performance to enable data-driven tuning of the Strategy Engine.

**Scope:**
*   **Metrics:** Track `forecast_error`, `cost_deviation`, and `battery_efficiency_realized`.
*   **Persistence:** Store daily metrics in `planner_learning.db`.
*   **Feedback:** Use these metrics to auto-adjust `s_index` or `wear_cost` baselines (Phase 3).

**Status:** Completed.
**Outcome:** `planner_learning.db` now tracks planned vs actuals.

### Rev K7 — The Mirror (Backfill & Visualization)

**Goal:** Ensure data continuity and visualize performance.

**Scope:**
*   Implement auto-backfill from HA on startup.
*   Create "Performance" tab in Web UI (SoC Tunnel, Cost Reality).

**Status:** Completed.

### Rev K8 — The Analyst (Grid Peak Shaving)

**Goal:** Implement "Grid Peak Shaving" to cap grid import peaks, avoiding high power tariffs or blown fuses.

**Scope:**
*   **Config:** Add `grid.import_limit_kw` (e.g., 11.0).
*   **Kepler:** Add hard constraint `grid_import_t <= limit`.
*   **Strategy:** Allow dynamic adjustment of this limit (e.g., "Vacation Mode" might lower it, or "Emergency" might raise it).

**Status:** Completed.

### [COMPLETED] Rev K9: The Learning Loop (Feedback)
**Goal:** Close the loop by analyzing forecast errors and adjusting planner parameters automatically.
- **Analyst:** New component to calculate bias (Forecast vs Actual).
- **Auto-Tune:** Write adjustments to `learning_daily_metrics`.
- **Status:** Completed. Analyst implemented and verified.

### [COMPLETED] Rev K10 — Aurora UI Makeover
**Goal:** Revamp the "Aurora" tab in the Web UI to serve as the central command center for the AI agent.
- **Scope:**
    - **Cockpit Layout:** High-density dashboard with "Bridge", "Radar", and "Log".
    - **Strategy Log:** Backend mechanism to log and display AI decisions.
    - **Context Radar:** Visualization of risk factors (Weather, Price, Forecast).
    - **Performance Mirror:** Merged "SoC Tunnel" and "Cost Reality" charts from deprecated Performance tab.
    - **Performance Mirror:** Merged "SoC Tunnel" and "Cost Reality" charts from deprecated Performance tab.
- **Status:** Completed.

### [COMPLETED] Rev K11 — Aurora Reflex (Long-Term Tuning)
**Goal:** Implement the "Inner Ear" of the system to auto-tune parameters based on long-term drift.
- **Scope:**
    - **Reflex Engine:** Daily analysis of Safety, Confidence, ROI, and Capacity.
    - **Safe Updates:** Use `ruamel.yaml` to preserve comments in `config.yaml`.
    - **UI:** Toggle control in Aurora Tab.
- **Status:** Completed.

### [COMPLETED] Rev K12 — Aurora Reflex Completion (The Analyzers)

**Goal:** Complete the placeholder analyzer implementations in `backend/learning/reflex.py` so that Aurora Reflex actually tunes parameters based on historical data.

**Background:** Rev K11 created the Reflex framework with `run()`, `update_config()`, and UI toggle. However, the four core analyzers (`analyze_safety`, `analyze_confidence`, `analyze_roi`, `analyze_capacity`) are stubs that return placeholder messages without querying data or proposing updates.

**Scope:**

#### Phase A: Safety Analyzer (`s_index.base_factor`)
*   **Signal:** Query `slot_observations` for low-SoC events (SoC < 5% during peak hours 16:00-20:00).
*   **Logic:**
    - Count days in last 30d with critical low-SoC events.
    - If > 3 events: propose `base_factor += 0.02` (max 1.3).
    - If 0 events for 60+ days: propose `base_factor -= 0.01` (min 1.0) to relax.
*   **Output:** `{"s_index.base_factor": new_value}` or empty dict.

#### Phase B: Confidence Analyzer (`forecasting.pv_confidence_percent`)
*   **Signal:** Compare `slot_forecasts.pv_forecast_kwh` vs `slot_observations.pv_kwh` over last 14 days.
*   **Logic:**
    - Calculate bias: `mean(forecast - actual)`.
    - If systematic over-prediction (bias > 0.5 kWh/slot avg): lower confidence → increase `pv_safety_margin`.
    - If systematic under-prediction (bias < -0.5 kWh/slot avg): we're too conservative.
*   **Output:** Tune `forecasting.pv_confidence_percent` (80-100 range).

#### Phase C: ROI Analyzer (`battery_economics.battery_cycle_cost_kwh`)
*   **Signal:** Calculate realized arbitrage profit vs battery cycles over last 30 days.
*   **Logic:**
    - Estimate: `profit = Σ(export_revenue - import_cost_for_charging)`.
    - Estimate: `cycles = Σ(charge_kwh) / battery_capacity`.
    - If `profit / cycles` is significantly higher than current `battery_cycle_cost_kwh`, we're being too conservative.
    - If lower, we're cycling too aggressively.
*   **Output:** Tune `battery_economics.battery_cycle_cost_kwh` (0.1-0.5 SEK range).

#### Phase D: Capacity Analyzer (`battery.capacity_kwh`)
*   **Signal:** Look for cliffs in SoC vs energy delivered.
*   **Logic:**
    - If SoC drops from 100% to 20% but only ~X kWh was discharged (vs expected ~0.8 * capacity), capacity has faded.
    - Use `Σ(discharge_kwh) / Δ(SoC%)` to estimate effective capacity.
*   **Output:** Tune `battery.capacity_kwh` (only decrease, never increase beyond nameplate).

#### Phase E: Guardrails & Rate Limits
*   **Hard Clamps:** Each parameter has min/max bounds.
*   **Rate Limits:** Max change per day (e.g., `base_factor` change ≤ 0.02/day).
*   **Audit Log:** Log all proposed/applied changes to `strategy_log` for visibility.

**Implementation Steps:**

1.  **Add Query Methods to LearningStore:**
    *   `get_low_soc_events(days_back, threshold_percent, peak_hours)` → returns count/list.
    *   `get_forecast_vs_actual(days_back, target='pv')` → returns DataFrame with paired data.
    *   `get_arbitrage_stats(days_back)` → returns profit, cycles, avg price spread.
    *   `get_capacity_estimate(days_back)` → returns estimated effective capacity.

2.  **Implement Analyzers in `reflex.py`:**
    *   Replace placeholder logic with actual queries and decision rules.
    *   Add `BOUNDS` and `MAX_DAILY_CHANGE` constants at top of file.

3.  **Add Audit Logging:**
    *   Call `append_strategy_event()` for each proposed/applied change.
    *   Show reflex activity in Aurora UI Strategy Log.

4.  **Testing:**
    *   Unit tests for each analyzer with mock data.
    *   Integration test: run `reflex.run(dry_run=True)` and verify proposals.

**Verification:**
*   **Unit Tests:** `tests/test_reflex.py` with fixture data covering edge cases.
*   **Dry Run:** `python -m backend.learning.reflex` should output sensible proposals.
*   **Production Validation:** Enable `learning.reflex_enabled`, monitor for 7 days, verify no wild swings.

**Status:** Completed.

### [COMPLETED] Rev K13 — Planner Modularization (Production Architecture)

**Goal:** Refactor the monolithic `planner.py` (3,637 lines) into a production-grade modular `planner/` package with clear separation of concerns, typed contracts, and testable components.

**Background:** The current `planner.py` is a "God class" containing input processing, legacy MPC logic, Kepler integration, S-Index calculation, water heating, learning hooks, and output formatting. This makes it difficult to test, understand, and extend.

**Target Architecture:**

```
planner/                          # NEW package
├── __init__.py                   # Public API: PlannerPipeline, generate_schedule()
├── pipeline.py                   # Main orchestrator (~200 lines)
│
├── inputs/                       # Input Layer
│   ├── __init__.py
│   ├── data_prep.py              # prepare_df(), price/forecast dataframe building
│   └── types.py                  # PlannerInput, SlotData, ForecastData dataclasses
│
├── strategy/                     # Strategy Layer (Aurora integration points)
│   ├── __init__.py
│   ├── s_index.py                # S-Index calculation & dynamic weights
│   ├── target_soc.py             # Inter-day target SoC logic
│   ├── overlays.py               # Learning overlays, Aurora bias corrections
│   └── manual_plan.py            # apply_manual_plan()
│
├── scheduling/                   # Pre-solver Scheduling
│   ├── __init__.py
│   ├── water_heating.py          # Water heater window selection
│   └── terminal_value.py         # Terminal value calculation
│
├── solver/                       # Kepler MILP
│   ├── __init__.py
│   ├── kepler.py                 # KeplerSolver (from backend/kepler/solver.py)
│   ├── adapter.py                # DataFrame ↔ Kepler types (from backend/kepler/)
│   └── types.py                  # KeplerConfig, KeplerInput, KeplerResult
│
├── output/                       # Output Layer
│   ├── __init__.py
│   ├── schedule.py               # Build schedule DataFrame, schedule.json
│   └── debug_payload.py          # Generate planner_debug JSON
│
└── observability/                # Cross-cutting
    ├── __init__.py
    ├── logging.py                # Structured planner logging
    └── learning_hook.py          # Training episode recording

archive/                          # Reference only (not imported)
└── legacy_mpc.py                 # Full 7-pass heuristic for historical reference
```

**Key Type Contracts:**

```python
# planner/inputs/types.py
@dataclass(frozen=True)
class SlotData:
    start_time: datetime
    import_price_sek: float
    export_price_sek: float
    pv_forecast_kwh: float
    load_forecast_kwh: float
    water_heater_kwh: float = 0.0

@dataclass(frozen=True)
class PlannerInput:
    horizon_start: datetime
    horizon_end: datetime
    slots: Tuple[SlotData, ...]
    initial_soc_percent: float
    battery_capacity_kwh: float
    context: Dict[str, Any]  # vacation_mode, weather, etc.

# planner/solver/types.py
@dataclass(frozen=True)
class KeplerResult:
    slots: Tuple[KeplerSlotResult, ...]
    objective_value: float
    status: str  # 'Optimal', 'Infeasible', 'Timeout'
    solve_time_ms: float
```

**Comparison Mode (Kepler ± Aurora):**
The pipeline will support a `mode` parameter:
*   `"full"` (default): Aurora overlays + Strategy + Kepler (production)
*   `"baseline"`: Kepler only, no Aurora overlays (for A/B comparison)

This allows comparing Aurora's contribution without involving Legacy MPC.

---

**Scope:**

#### Phase A: Preparation & Types
*   Create `planner/` package directory structure.
*   Define all dataclass types in `planner/inputs/types.py` and `planner/solver/types.py`.
*   Ensure frozen dataclasses for immutability.
*   Add `planner/__init__.py` with public API stub.

#### Phase B: Input Layer Extraction
*   Extract from `planner.py`:
    *   `_normalize_timestamp()` → `planner/inputs/data_prep.py`
    *   `_build_price_dataframe()` → `planner/inputs/data_prep.py`
    *   `_build_forecast_dataframe()` → `planner/inputs/data_prep.py`
    *   `prepare_df()` → `planner/inputs/data_prep.py`
*   Add function to convert DataFrame → `PlannerInput` dataclass.
*   Unit tests: `tests/planner/test_data_prep.py`.

#### Phase C: Strategy Layer Extraction
*   Extract from `HeliosPlanner`:
    *   `_calculate_s_index()` → `planner/strategy/s_index.py`
    *   `_calculate_dynamic_target_soc()` → `planner/strategy/target_soc.py`
    *   `_load_learning_overlays()` → `planner/strategy/overlays.py`
    *   `apply_manual_plan()` → `planner/strategy/manual_plan.py`
*   Unit tests: `tests/planner/test_s_index.py`, `tests/planner/test_target_soc.py`.

#### Phase D: Scheduling Layer Extraction
*   Extract from `HeliosPlanner`:
    *   Water heating window selection logic → `planner/scheduling/water_heating.py`
    *   `_calculate_terminal_value()` → `planner/scheduling/terminal_value.py`
*   Unit tests: `tests/planner/test_water_heating.py`.

#### Phase E: Solver Migration
*   Move from `backend/kepler/`:
    *   `solver.py` → `planner/solver/kepler.py`
    *   `adapter.py` → `planner/solver/adapter.py`
    *   `types.py` → `planner/solver/types.py`
*   Update adapter to work with new dataclass types.
*   Delete `backend/kepler/` directory after migration.
*   Unit tests: Update existing Kepler tests to new paths.

#### Phase F: Output Layer Extraction
*   Extract from `HeliosPlanner`:
    *   Schedule DataFrame building → `planner/output/schedule.py`
    *   `_record_debug_payload()` → `planner/output/debug_payload.py`
*   Unit tests: `tests/planner/test_schedule_output.py`.

#### Phase G: Observability Layer
*   Extract from `HeliosPlanner`:
    *   Logging configuration → `planner/observability/logging.py`
    *   Training episode recording → `planner/observability/learning_hook.py`
*   Integrate with existing `LearningEngine`.

#### Phase H: Pipeline Orchestrator
*   Create `planner/pipeline.py` with:
    *   `PlannerPipeline` class that orchestrates all layers.
    *   `generate_schedule(input_data, config, mode="full")` main entry point.
    *   Clear step-by-step flow with logging at each stage.
*   Less than 200 lines of orchestration code.

#### Phase I: Legacy Archival & Cleanup
*   Copy full legacy 7-pass heuristic logic to `archive/legacy_mpc.py`.
*   Add docstring explaining it's archived for reference, not imported.
*   Delete monolithic `planner.py`.
*   Update all imports across codebase:
    *   `backend/webapp.py`
    *   `backend/scheduler.py`
    *   `bin/` scripts
    *   `tests/`
*   Verify no remaining references to old `planner.py`.

#### Phase J: Integration Testing
*   Create `tests/planner/test_integration.py`:
    *   Test full pipeline produces valid schedule.
    *   Test `mode="full"` vs `mode="baseline"` both work.
    *   Test schedule.json output matches expected schema.
*   Run existing tests to ensure backward compatibility.

---

**Implementation Steps:**

1.  **Create Package Structure:**
    *   `mkdir -p planner/{inputs,strategy,scheduling,solver,output,observability}`
    *   Create all `__init__.py` files.

2.  **Define Types First (Phase A):**
    *   Implement all dataclasses before extracting logic.
    *   This forces clear interfaces between modules.

3.  **Extract Layer by Layer (Phases B-G):**
    *   For each extraction:
        1.  Copy function to new module.
        2.  Adapt to use new types.
        3.  Add unit test.
        4.  Update old `planner.py` to import from new module.
        5.  Run full test suite.
    *   This ensures working code at every step.

4.  **Build Orchestrator (Phase H):**
    *   Once all pieces are extracted, build the pipeline.
    *   Replace `HeliosPlanner.generate_schedule()` with `PlannerPipeline`.

5.  **Archive & Cleanup (Phase I):**
    *   Only after full pipeline works, archive legacy.
    *   Global search-replace of imports.

6.  **Final Validation (Phase J):**
    *   Run all tests.
    *   Manual test: Run planner, check schedule.json, verify UI works.

---

**Verification:**

*   **Unit Tests:**
    *   `tests/planner/test_data_prep.py` — Input layer.
    *   `tests/planner/test_s_index.py` — S-Index calculation.
    *   `tests/planner/test_target_soc.py` — Target SoC logic.
    *   `tests/planner/test_water_heating.py` — Water heating.
    *   `tests/planner/test_schedule_output.py` — Output formatting.
    *   Run: `PYTHONPATH=. python -m pytest tests/planner/ -v`

*   **Integration Tests:**
    *   `tests/planner/test_integration.py` — Full pipeline.
    *   Run: `PYTHONPATH=. python -m pytest tests/planner/test_integration.py -v`

*   **Existing Test Suite:**
    *   Run: `PYTHONPATH=. python -m pytest -q`
    *   All existing tests must pass.

*   **Manual Validation:**
    1.  Start dev server: `npm run dev`
    2.  Trigger planner run via UI or: `python -c "from planner import generate_schedule; ..."`
    3.  Verify `schedule.json` is created and valid.
    4.  Check Dashboard displays schedule correctly.
    5.  Verify Aurora tab shows Kepler debug info.

**Status:** Not Started.

---

## Backlog

### ⏸️ On Hold

### Rev 63 — Export What-If Simulator (Lab Prototype)
*   **Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.
*   **Status:** On Hold (Prototype exists but parked for Kepler pivot).


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
