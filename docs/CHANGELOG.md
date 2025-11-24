# Darkstar Project History & Changelog

This document contains the archive of all completed revisions. It serves as the historical record of technical decisions and implemented features.

---

## Phase 4: Strategy Engine & Aurora v2 (The Agent)

### Rev 62 — Export Safety & Aurora Agent
*   **Summary:** Decoupled battery export from `strategic_charging.target_soc_percent` and removed the non-decreasing responsibility gate so export can occur whenever price is profitable and SoC is above the protective export floor.
*   **Details:**
    *   Export now uses only `protective_soc_kwh` (gap-based or fixed) plus profitability checks, instead of treating the strategic charge target as a hard export floor.
    *   Removed the redundant `responsibilities_met` guard, which previously never resolved and effectively disabled automatic export despite high spreads.
*   **Status:** ✅ Completed (2025-11-24)

### Rev 61 — The Aurora Tab (AI Agent Interface)
*   **Summary:** Introduced the Aurora tab (`/aurora`) as the system's "Brain" and Command Center. The tab explains *why* decisions are made, visualizes Aurora’s forecast corrections, and exposes a high-level risk control surface (S-index).
*   **Backend:** Added `backend/api/aurora.py` and registered `aurora_bp` in `backend/webapp.py`. Implemented:
    *   `GET /api/aurora/dashboard` — returns identity (Graduation level from `learning_runs`), risk profile (persona derived from `s_index.base_factor`), weather volatility (via `ml.weather.get_weather_volatility`), a 48h horizon of base vs corrected forecasts (PV + load), and the last 14 days of per-day correction volume (PV + load, with separate fields).
    *   `POST /api/aurora/briefing` — calls the LLM (via OpenRouter) with the dashboard JSON to generate a concise 1–2 sentence Aurora “Daily Briefing”.
*   **Frontend Core:** Extended `frontend/src/lib/types.ts` and `frontend/src/lib/api.ts` with `AuroraDashboardResponse`, history types, and `Api.aurora.dashboard/briefing`.
*   **Aurora UI:**
    *   Built `frontend/src/pages/Aurora.tsx` as a dedicated Command Center:
        *   Hero card with shield avatar, Graduation mode, Experience (runs), Strategy (risk persona + S-index factor), Today’s Action (kWh corrected), and a volatility-driven visual “signal”.
        *   Daily Briefing card that renders the LLM output as terminal-style system text.
        *   Risk Dial module wired to `s_index.base_factor`, with semantic regions (Gambler / Balanced / Paranoid), descriptive copy, and inline color indicator.
    *   Implemented `frontend/src/components/DecompositionChart.tsx` (Chart.js) for a 48h Forecast Decomposition:
        *   Base Forecast: solid line with vertical gradient area fill.
        *   Final Forecast: thicker dashed line.
        *   Correction: green (positive) / red (negative) bars, with the largest correction visually highlighted.
    *   Implemented `frontend/src/components/CorrectionHistoryChart.tsx`:
        *   Compact bar chart over 14 days of correction volume, with tooltip showing Date + Total kWh.
        *   Trend text summarizing whether Aurora has been more or less active in the last week vs the previous week.
*   **UX Polish:** Iterated on gradients, spacing, and hierarchy so the Aurora tab feels like a high-end agent console rather than a debugging view, while keeping the layout consistent with Dashboard/Forecasting (hero → decomposition → impact).
*   **Status:** ✅ Completed (2025-11-24)

### Rev 60 — Cross-Day Responsibility (Charging Ahead for Tomorrow)
*   **Summary:** Updated `_pass_1_identify_windows` to consider total future net deficits vs. cheap-window capacity and expand cheap windows based on future price distribution when needed, so the planner charges in the cheapest remaining hours and preserves SoC for tomorrow’s high-price periods even when the battery is already near its target at runtime.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 59 — Intelligent Memory (Aurora Correction)
*   **Summary:** Implemented Aurora Correction (Model 2) with a strict Graduation Path (Infant/Statistician/Graduate) so the system can predict and apply forecast error corrections safely as data accumulates.
*   **Details:** Extended `slot_forecasts` with `pv_correction_kwh`, `load_correction_kwh`, and `correction_source`; added `ml/corrector.py` to compute residual-based corrections using Rolling Averages (Level 1) or LightGBM error models (Level 2) with ±50% clamping around the base forecast; implemented `ml/pipeline.run_inference` to orchestrate base forecasts (Model 1) plus corrections (Model 2) and persist them in SQLite; wired `inputs.py` to consume `base + correction` transparently when building planner forecasts.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 58 — The Weather Strategist (Strategy Engine)
*   **Summary:** Added a weather volatility metric over a 48h horizon using Open-Meteo (cloud cover and temperature), wired it into `inputs.py` as `context.weather_volatility`, and taught the Strategy Engine to increase `s_index.pv_deficit_weight` and `temp_weight` linearly with volatility while never dropping below `config.yaml` baselines.
*   **Details:** `ml/weather.get_weather_volatility` computes normalized scores (`0.0-1.0`) based on standard deviation, `inputs.get_all_input_data` passes them as `{"cloud": x, "temp": y}`, and `backend.strategy.engine.StrategyEngine` scales weights by up to `+0.4` (PV deficit) and `+0.2` (temperature) with logging and a debug harness in `debug/test_strategy_weather.py`.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 57 — In-App Scheduler Orchestrator
*   **Summary:** Implemented a dedicated in-app scheduler process (`backend/scheduler.py`) controlled by `automation.schedule` in `config.yaml`, exposed `/api/scheduler/status`, and wired the Dashboard’s Planner Automation card to show real last/next run status instead of computed guesses.
*   **Status:** ✅ Completed (2025-11-23)

### Rev 56 — Dashboard Server Plan Visualization
*   **Summary:** Added a “Load DB plan” Quick Action, merged execution history into `/api/db/current_schedule`, and let the Dashboard chart show `current_schedule` slots with actual SoC/`actual_*` values without overwriting `schedule.json`.
*   **Status:** ✅ Completed (2025-11-23)

### Rev A23 — The Voice (Smart Advisor)
*   **Summary:** Present the Analyst's findings via a friendly "Assistant" using an LLM.
*   **Scope:** `secrets.yaml` (OpenRouter Key), `backend/llm_client.py` (Gemini Flash interface), UI "Smart Advisor" card.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A22 — The Analyst (Manual Load Optimizer)
*   **Summary:** Calculate the mathematically optimal time to run heavy appliances (Dishwasher, Dryer) over the next 48h.
*   **Logic:** Scans price/PV forecast to find "Golden Windows" (lowest cost for 3h block). Outputs a JSON recommendation.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A21 — "The Lab" (Simulation Playground)
*   **Summary:** Added `/api/simulate` support for overrides and created `Lab.tsx` UI for "What If?" scenarios (e.g., Battery Size, Max Power).
*   **Status:** ✅ Completed (2025-11-21)

### Rev A20 — Smart Thresholds (Dynamic Window Expansion)
*   **Summary:** Updated `_pass_1_identify_windows` in `planner.py`. Logic now calculates energy deficit vs window capacity and expands the "cheap" definition dynamically to meet `target_soc`.
*   **Validation:** `debug/test_smart_thresholds.py` simulated a massive 100kWh empty battery with a strict 5% price threshold. Planner successfully expanded the window from ~10 slots to 89 slots to meet demand.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A19 — Context Awareness
*   **Summary:** Connected `StrategyEngine` to `inputs.py`. Implemented `VacationMode` rule (disable water heating).
*   **Fixes:** Rev 19.1 hotfix removed `alarm_armed` from water heating disable logic (occupants need hot water).
*   **Status:** ✅ Completed (2025-11-21)

### Rev A18 — Strategy Injection Interface
*   **Summary:** Refactored `planner.py` to accept runtime config overrides. Created `backend/strategy/engine.py`. Added `strategy_log` table.
*   **Status:** ✅ Completed (2025-11-20)

---

## Phase 3: Aurora v1 (Machine Learning Foundation)

### Rev A17 — Stabilization & Automation
*   **Summary:** Diagnosed negative bias (phantom charging), fixed DB locks, and automated the ML inference pipeline.
*   **Key Fixes:**
    *   **Phantom Charging:** Added `.clip(lower=0.0)` to adjusted forecasts.
    *   **S-Index:** Extended input horizon to 7 days to ensure S-index has data.
    *   **Automation:** Modified `inputs.py` to auto-run `ml/forward.py` if Aurora is active.
*   **Status:** ✅ Completed (2025-11-21)

### Rev A16 — Calibration & Safety Guardrails
*   **Summary:** Added planner-facing guardrails (load > 0.01, PV=0 at night) to prevent ML artifacts from causing bad scheduling.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A15 — Forecasting Tab Enhancements
*   **Summary:** Refined the UI to compare Baseline vs Aurora MAE metrics. Added "Run Eval" and "Run Forward" buttons to the UI.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A14 — Additional Weather Features
*   **Summary:** Enriched LightGBM models with Cloud Cover and Shortwave Radiation from Open-Meteo.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A13 — Naming Cleanup
*   **Summary:** Standardized UI labels to "Aurora (ML Model)" and moved the forecast source toggle to the Forecasting tab.
*   **Status:** ✅ Completed (2025-11-18)

### Rev A12 — Settings Toggle
*   **Summary:** Exposed `forecasting.active_forecast_version` in Settings to switch between Baseline and Aurora.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A11 — Planner Consumption
*   **Summary:** Wired `inputs.py` to consume Aurora forecasts when the feature flag is active.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A10 — Forward Inference
*   **Summary:** Implemented `ml/forward.py` to generate future forecasts using Open-Meteo forecast data.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A09 — Aurora v0.2 (Enhanced Shadow Mode)
*   **Summary:** Added temperature and vacation mode features to training. Added Forecasting UI tab.
*   **Status:** ✅ Completed (2025-11-17)

### Rev A01–A08 — Aurora Initialization
*   **Summary:** Established `/ml` directory, data activators (`ml/data_activator.py`), training scripts (`ml/train.py`), and evaluation scripts (`ml/evaluate.py`).
*   **Status:** ✅ Completed (2025-11-16)

---

## Phase 2: Modern Core (Monorepo & React UI)

### Rev 55 — Production Readiness
*   **Summary:** Added global "Backend Offline" indicator, improved mobile responsiveness, and cleaned up error handling.
*   **Status:** ✅ Completed (2025-11-15)

### Rev 54 — Learning & Debug Enhancements
*   **Summary:** Persisted S-Index history and improved Learning tab charts (dual-axis for changes vs. s-index). Added time-range filters to Debug logs.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 53 — Learning Architecture
*   **Summary:** Consolidated learning outputs into `learning_daily_metrics` (one row per day). Planner now reads learned overlays (PV/Load bias) from DB.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 52 — Learning History
*   **Summary:** Created `learning_param_history` to track config changes over time without modifying `config.yaml`.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 51 — Learning Engine Debugging
*   **Summary:** Traced data flow issues. Implemented real HA sensor ingestion for observations (`sensor_totals`) to fix "zero bias" issues.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 50 — Planning & Settings Polish
*   **Summary:** Handled "zero-capacity" gaps in Planning Timeline. Added explicit field validation in Settings UI.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 49 — Device Caps & SoC Enforcement
*   **Summary:** Planning tab now validates manual plans against device limits (max kW) and SoC bounds via `api/simulate`.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 48 — Dashboard History Merge
*   **Summary:** Dashboard "Today" chart now merges planned data with actual execution history from MariaDB (SoC Actual line).
*   **Status:** ✅ Completed (2025-11-14)

### Rev 47 — UX Polish
*   **Summary:** Simplified Dashboard chart (removed Y-axis labels, moved to overlay pills). Normalized Planning timeline background.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 46 — Schedule Correctness
*   **Summary:** Fixed day-slicing bugs (charts now show full 00:00–24:00 window). Verified Planner->DB->Executor contract.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 45 — Debug UI
*   **Summary:** Built dedicated Debug tab with log viewer (ring buffer) and historical SoC mini-chart.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 44 — Learning UI
*   **Summary:** Built Learning tab (Status, Metrics, History). Surfaces "Learning Enabled" status and recent run stats.
*   **Status:** ✅ Completed (2025-11-14)

### Rev 43 — Settings UI
*   **Summary:** Consolidated System, Parameters, and UI settings into a React form. Added "Reset to Defaults" and Theme Picker.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 42 — Planning Timeline
*   **Summary:** Rebuilt the interactive Gantt chart in React. Supports manual block CRUD (Charge/Water/Export/Hold) and Simulate/Save flow.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 41 — Dashboard Hotfixes
*   **Summary:** Fixed Chart.js DOM errors and metadata sync issues ("Now Showing" badge).
*   **Status:** ✅ Completed (2025-11-13)

### Rev 40 — Dashboard Completion
*   **Summary:** Full parity with legacy UI. Added Quick Actions (Run Planner, Push to DB), Dynamic KPIs, and Real-time polling.
*   **Status:** ✅ Completed (2025-11-13)

### Rev 39 — React Scaffold
*   **Summary:** Established `frontend/` structure (Vite + React). Built the shell (Sidebar, Header) and basic ChartCard.
*   **Status:** ✅ Completed (2025-11-12)

### Rev 38 — Dev Ergonomics
*   **Summary:** Added `npm run dev` to run Flask and Vite concurrently with a proxy.
*   **Status:** ✅ Completed (2025-11-12)

### Rev 62 — Export Safety & Aurora Agent
*   **Summary:** Decoupled battery export from `strategic_charging.target_soc_percent` and removed the non-decreasing responsibility gate so export can occur whenever price is profitable and SoC is above the protective export floor.
*   **Details:**
    *   Export now uses only `protective_soc_kwh` (gap-based or fixed) plus profitability checks, instead of treating the strategic charge target as a hard export floor.
    *   Removed the redundant `responsibilities_met` guard, which previously never resolved and effectively disabled automatic export despite high spreads.
*   **Status:** ✅ Completed (2025-11-24)

### Rev 37 — Monorepo Skeleton
*   **Summary:** Moved Flask app to `backend/` and React app to `frontend/`.
*   **Status:** ✅ Completed (2025-11-12)

---

## Phase 1: Foundations (Revs 0–36)

*   **Core MPC**: Robust multi-pass logic (safety margins, window detection, cascading responsibility, hold logic).
*   **Water Heating**: Integrated daily quota scheduling (grid-preferred in cheap windows).
*   **Export**: Peak-only export logic and profitability guards.
*   **Manual Planning**: Semantics for manual blocks (Charge/Water/Export/Hold) merged with MPC.
*   **Infrastructure**: SQLite learning DB, MariaDB history sync, Nordpool/HA integration.
