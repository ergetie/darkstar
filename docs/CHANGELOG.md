# Darkstar Project History & Changelog

This document contains the archive of all completed revisions. It serves as the historical record of technical decisions and implemented features.

---

## Phase 7: Kepler Era (MILP Planner Maturation)

This phase promoted Kepler from shadow mode to primary planner, implemented strategic S-Index, and built out the learning/reflex systems.

### Rev K15 — Probabilistic Forecasting (Risk Awareness)
- Upgraded Aurora Vision from point forecasts to probabilistic forecasts (p10/p50/p90).
- Trained Quantile Regression models in LightGBM.
- Updated DB schema for probabilistic bands.
- Enabled `probabilistic` S-Index mode using p90 load and p10 PV.
- **Status:** ✅ Completed

### Rev K14 — Astro-Aware PV (Forecasting)
- Replaced hardcoded PV clamps (17:00-07:00) with dynamic sunrise/sunset calculations using `astral`.
- **Status:** ✅ Completed

### Rev K13 — Planner Modularization (Production Architecture)
- Refactored monolithic `planner.py` (3,637 lines) into modular `planner/` package.
- Clear separation: inputs → strategy → scheduling → solver → output.
- **Status:** ✅ Completed

### Rev K12 — Aurora Reflex Completion (The Analyzers)
- Completed Safety, Confidence, ROI, and Capacity analyzers in `reflex.py`.
- Added query methods to LearningStore for historical analysis.
- **Status:** ✅ Completed

### Rev K11 — Aurora Reflex (Long-Term Tuning)
- Implemented "Inner Ear" for auto-tuning parameters based on long-term drift.
- Safe config updates with `ruamel.yaml`.
- **Status:** ✅ Completed

### Rev K10 — Aurora UI Makeover
- Revamped Aurora tab as central AI command center.
- Cockpit layout with Strategy Log, Context Radar, Performance Mirror.
- **Status:** ✅ Completed

### Rev K9 — The Learning Loop (Feedback)
- Analyst component to calculate bias (Forecast vs Actual).
- Auto-tune adjustments written to `learning_daily_metrics`.
- **Status:** ✅ Completed

### Rev K8 — The Analyst (Grid Peak Shaving)
- Added `grid.import_limit_kw` to cap grid import peaks.
- Hard constraint in Kepler solver.
- **Status:** ✅ Completed

### Rev K7 — The Mirror (Backfill & Visualization)
- Auto-backfill from HA on startup.
- Performance tab with SoC Tunnel and Cost Reality charts.
- **Status:** ✅ Completed

### Rev K6 — The Learning Engine (Metrics & Feedback)
- Tracking `forecast_error`, `cost_deviation`, `battery_efficiency_realized`.
- Persistence in `planner_learning.db`.
- **Status:** ✅ Completed

### Rev K5 — Strategy Engine Expansion (The Tuner)
- Dynamic tuning of `wear_cost`, `ramping_cost`, `export_threshold` based on context.
- **Status:** ✅ Completed

### Rev K4 — Kepler Vision & Benchmarking
- Benchmarked MCP vs Kepler plans.
- S-Index parameter tuning.
- **Status:** ✅ Completed

### Rev K3 — Strategic S-Index (Decoupled Strategy)
- Decoupled Load Inflation (intra-day) from Dynamic Target SoC (inter-day).
- UI display of S-Index and Target SoC.
- **Status:** ✅ Completed

### Rev K2 — Kepler Promotion (Primary Planner)
- Promoted Kepler to primary planner via `config.kepler.primary_planner`.
- **Status:** ✅ Completed

---

## Phase 6: Kepler (MILP Planner)

### Rev K1 — Kepler Foundation (MILP Solver)
*   **Goal:** Implement the core Kepler MILP solver as a production-grade component, replacing the `ml/benchmark/milp_solver.py` prototype, and integrate it into the backend for shadow execution.
*   **Status:** Completed (Kepler backend implemented in `backend/kepler/`, integrated into `planner.py` in shadow mode, and verified against MPC on historical data with ~16.8% cost savings).

## Phase 5: Antares (Archived / Pivoted to Kepler)

### Rev 84 — Antares RL v2 Lab (Sequence State + Model Search)
*   **Goal:** Stand up a dedicated RL v2 “lab” inside the repo with a richer, sequence-based state and a clean place to run repeated BC/PPO experiments until we find a policy that consistently beats MPC on a wide held-out window.
*   **Status:** In progress (RL v2 contract + env + BC v2 train/eval scripts are available under `ml/rl_v2/`; BC v2 now uses SoC + cost‑weighted loss and plots via `debug/plot_day_mpc_bcv2_oracle.py`. A lab‑only PPO trainer (`ml/rl_v2/train_ppo_v2.py` + `AntaresRLEnvV2`) and cost eval (`ml/rl_v2/eval_ppo_v2_cost.py`) are available with shared SoC drift reporting across MPC/PPO/Oracle. PPO v2 is currently a lab artefact only: it can outperform MPC under an Oracle‑style terminal SoC penalty but does not yet match Oracle’s qualitative behaviour on all days. RL v2 remains off the planner hot path; focus for production planning is converging on a MILP‑centric planner as described in `docs/darkstar_milp.md`, with RL/BC used for lab diagnostics and policy discovery.)

### Rev 83 — RL v1 Stabilisation and RL v2 Lab Split
*   **Goal:** Stabilise RL v1 as a diagnostics-only baseline for Darkstar v2, ensure MPC remains the sole production decision-maker, and carve out a clean space (branch + tooling) for RL v2 experimentation without risking core planner behaviour.
*   **Status:** In progress (shadow gating added for RL, documentation to be extended and RL v2 lab to be developed on a dedicated branch).

### Rev 82 — Antares RL v2 (Oracle-Guided Imitation)
*   **Goal:** Train an Antares policy that consistently beats MPC on historical tails by directly imitating the Oracle MILP decisions, then evaluating that imitation policy in the existing AntaresMPCEnv.
*   **Status:** In progress (BC training script, policy wrapper, and evaluation wiring to be added; first goal is an Oracle-guided policy that matches or beats MPC on the 2025-11-18→27 tail window).

### Rev 81 — Antares RL v1.1 (Horizon-Aware State + Terminal SoC Shaping)
*   **Goal:** Move RL from locally price-aware to day-aware so it charges enough before known evening peaks and avoids running empty too early, while staying within the existing AntaresMPCEnv cost model.
*   **Status:** In progress (state and shaping changes wired in; next step is to retrain RL v1.1 and compare cost/behaviour vs the Rev 80 baseline).

### Rev 80 — RL Price-Aware Gating (Phase 4/5)
*   **Goal:** Make the v1 Antares RL agent behave economically sane per-slot (no discharging in cheap hours, prefer charging when prices are low, prefer discharging when prices are high), while keeping the core cost model and Oracle/MPC behaviour unchanged.
*   **Status:** Completed (price-aware gating wired into `AntaresMPCEnv` RL overrides, MPC/Oracle behaviour unchanged, and `debug/inspect_mpc_rl_oracle_stats.py` available to quickly compare MPC/RL/Oracle charge/discharge patterns against the day’s price distribution).

### Rev 79 — RL Visual Diagnostics (MPC vs RL vs Oracle)
*   **Goal:** Provide a simple, repeatable way to visually compare MPC, RL, and Oracle behaviour for a single day (battery power, SoC, prices, export) in one PNG image so humans can quickly judge whether the RL agent is behaving sensibly relative to MPC and the Oracle.
*   **Status:** Completed (CLI script `debug/plot_day_mpc_rl_oracle.py` added; generates and opens a multi-panel PNG comparing MPC vs RL vs Oracle for a chosen day using the same schedules used in cost evaluation).

### Rev 78 — Tail Zero-Price Repair (Phase 3/4)
*   **Goal:** Ensure the recent tail of the historical window (including November 2025) has no bogus zero import prices on otherwise normal days, so MPC/RL/Oracle cost evaluations are trustworthy.
*   **Status:** Completed (zero-price slots repaired via `debug/fix_zero_price_slots.py`; tail days such as 2025-11-18 → 2025-11-27 now have realistic 15-minute prices with no zeros, and cost evaluations over this window are trusted).

### Rev 77 — Antares RL Diagnostics & Reward Shaping (Phase 4/5)
*   **Goal:** Add tooling and light reward shaping so we can understand what the RL agent is actually doing per slot and discourage clearly uneconomic behaviour (e.g. unnecessary discharging in cheap hours), without changing the core cost definition used for evaluation.
*   **Status:** Completed (diagnostic tools and mild price-aware discharge penalty added; RL evaluation still uses the unshaped cost function, and the latest PPO v1 baseline is ~+8% cost vs MPC over recent tail days with Oracle as the clear lower bound).

### Rev 76 — Antares RL Agent v1 (Phase 4/5)
*   **Goal:** Design, train, and wire up the first real Antares RL agent (actor–critic NN) that uses the existing AntaresMPCEnv, cost model, and shadow plumbing, so we can evaluate a genuine learning-based policy in parallel with MPC and Oracle on historical data and (via shadow mode) on live production days.
*   **Status:** Completed (RL v1 agent scaffolded with PPO, RL runs logged to `antares_rl_runs`, models stored under `ml/models/antares_rl_v1/...`, evaluation script `ml/eval_antares_rl_cost.py` in place; latest RL baseline run is ~+8% cost vs MPC over recent tail days with Oracle as clear best, ready for further tuning in Rev 77+).

### Rev 75 — Antares Shadow Challenger v1 (Phase 4)
*   **Goal:** Run the latest Antares policy in shadow mode alongside the live MPC planner, persist daily shadow schedules with costs, and provide basic tooling to compare MPC vs Antares on real production data (no hardware control yet).
*   **Status:** Planned (first Phase 4 revision; enables production shadow runs and MPC vs Antares cost comparison on real data).

### Rev 74 — Tail Window Price Backfill & Final Data Sanity (Phase 3)
*   **Goal:** Fix and validate the recent tail of the July–now window (e.g. late November days with zero prices) so Phase 3 ends with a fully clean, production-grade dataset for both MPC and Antares training/evaluation.
*   **Status:** Planned (final Phase 3 data-cleanup revision before Phase 4 / shadow mode).

### Rev 73 — Antares Policy Cost Evaluation & Action Overrides (Phase 3)
*   **Goal:** Evaluate the Antares v1 policy in terms of full-day cost (not just action MAE) by letting it drive the Gym environment, and compare that cost against MPC and the Oracle on historical days.
*   **Status:** Planned (next active Antares revision; will produce a cost-based policy vs MPC/Oracle benchmark).

### Rev 72 — Antares v1 Policy (First Brain) (Phase 3)
*   **Goal:** Train a first Antares v1 policy that leverages the Gym environment and/or Oracle signals to propose battery/export actions and evaluate them offline against MPC and the Oracle.
*   **Status:** Completed (offline MPC-imitating policy, training, eval, and contract implemented in Rev 72).

### Rev 71 — Antares Oracle (MILP Benchmark) (Phase 3)
*   **Goal:** Build a deterministic “Oracle” that computes the mathematically optimal daily schedule (under perfect hindsight) so we can benchmark MPC and future Antares agents against a clear upper bound.
*   **Status:** Completed (Oracle MILP solver, MPC comparison tool, and config wiring implemented in Rev 71).

### Rev 70 — Antares Gym Environment & Cost Reward (Phase 3)
*   **Goal:** Provide a stable Gym-style environment around the existing deterministic simulator and cost model so any future Antares agent (supervised or RL) can be trained and evaluated offline on historical data.
*   **Status:** Completed (environment, reward, docs, and debug runner implemented in Rev 70).

### Rev 69 — Antares v1 Training Pipeline (Phase 3)
*   **Goal:** Train the first Antares v1 supervised model that imitates MPC’s per-slot decisions on validated `system_id="simulation"` data (battery + export focus) and establishes a baseline cost performance.
*   **Status:** Completed (training pipeline, logging, and eval helper implemented in Rev 69).

## Phase 5: Antares Phase 1–2 (Data & Simulation)

### Rev 68 — Antares Phase 2b: Simulation Episodes & Gym Interface
*   **Summary:** Turned the validated historical replay engine into a clean simulation episode dataset (`system_id="simulation"`) and a thin environment interface for Antares, plus a stable v1 training dataset API.
*   **Details:**
    *   Ran `bin/run_simulation.py` over the July–now window, gated by `data_quality_daily`, to generate and log ~14k simulation episodes into SQLite `training_episodes` and MariaDB `antares_learning` with `system_id="simulation"`, `episode_start_local`, `episode_date`, and `data_quality_status`.
    *   Added `ml/simulation/env.py` (`AntaresMPCEnv`) to replay MPC schedules as a simple Gym-style environment with `reset(day)` / `step(action)`.
    *   Defined `docs/ANTARES_EPISODE_SCHEMA.md` as the canonical episode + slot schema and implemented `ml/simulation/dataset.py` to build a battery-masked slot-level training dataset.
    *   Exposed a stable dataset API via `ml.api.get_antares_slots(dataset_version="v1")` and added `ml/train_antares.py` as the canonical training entrypoint (currently schema/stats only).
*   **Status:** ✅ Completed (2025-11-29)

### Rev 67 — Antares Data Foundation: Live Telemetry & Backfill Verification (Phase 2.5)
*   **Summary:** Hardened the historical data window (July 2025 → present) so `slot_observations` in `planner_learning.db` is a HA-aligned, 15-minute, timezone-correct ground truth suitable for replay and Antares training, and added explicit data-quality labels and mirroring tools.
*   **Details:**
    *   Extended HA LTS backfill (`bin/backfill_ha.py`) to cover load, PV, grid import/export, and battery charge/discharge, and combined it with `ml.data_activator.etl_cumulative_to_slots` for recent days and water heater.
    *   Introduced `debug/validate_ha_vs_sqlite_window.py` to compare HA hourly `change` vs SQLite hourly sums and classify days as `clean`, `mask_battery`, or `exclude`, persisting results in `data_quality_daily` (138 clean, 10 mask_battery, 1 exclude across 2025-07-03 → 2025-11-28).
    *   Added `debug/repair_missing_slots.py` to insert missing 15-minute slots for edge-case days (e.g. 2025-11-16) before re-running backfill.
    *   Ensured `backend.recorder` runs as an independent 15-minute loop in dev and server so future live telemetry is always captured at slot resolution, decoupled from planner cadence.
    *   Implemented `debug/mirror_simulation_episodes_to_mariadb.py` so simulation episodes (`system_id="simulation"`) logged in SQLite can be reliably mirrored into MariaDB `antares_learning` after DB outages.
*   **Status:** ✅ Completed (2025-11-28)

### Rev 66 — Antares Phase 2: The Time Machine (Simulator)
*   **Summary:** Built the historical replay engine that runs the planner across past days to generate training episodes, using HA history (LTS + raw) and Nordpool prices to reconstruct planner-ready state.
*   **Details:**
    *   Added `ml/simulation/ha_client.py` to fetch HA Long Term Statistics (hourly) for load/PV and support upsampling to 15-minute slots.
    *   Implemented `ml/simulation/data_loader.py` to orchestrate price/sensor loading, resolution alignment, and initial state reconstruction for simulation windows.
    *   Implemented `bin/run_simulation.py` to step through historical windows, build inputs, call `HeliosPlanner.generate_schedule(record_training_episode=True)`, and surface per-slot debug logs.
*   **Status:** ✅ Completed (2025-11-28)

### Rev 65 — Antares Phase 1b: The Data Mirror
*   **Summary:** Enabled dual-write of training episodes to a central MariaDB `antares_learning` table, so dev and prod systems share a unified episode lake.
*   **Details:**
    *   Added `system.system_id` to `config.yaml` and wired it into `LearningEngine.log_training_episode` / `_mirror_episode_to_mariadb`.
    *   Created the `antares_learning` schema in MariaDB to mirror `training_episodes` plus `system_id`.
    *   Ensured MariaDB outages do not affect planner runs by fully isolating mirror errors.
*   **Status:** ✅ Completed (2025-11-17)

### Rev 64 — Antares Phase 1: Unified Data Collection (The Black Box)
*   **Summary:** Introduced the `training_episodes` table and logging helper so planner runs can be captured as consistent episodes (inputs + context + schedule) for both live and simulated data.
*   **Details:**
    *   Added `training_episodes` schema in SQLite and `LearningEngine.log_training_episode` to serialize planner inputs/context/schedule.
    *   Wired `record_training_episode=True` into scheduler and CLI entrypoints while keeping web UI simulations clean.
    *   Updated cumulative ETL gap handling and tests to ensure recorded episodes are based on accurate slot-level data.
*   **Status:** ✅ Completed (2025-11-16)

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

---


