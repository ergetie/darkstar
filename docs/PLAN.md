# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

No active Antares Phase 2 revisions. Phase 2 (Rev 64–68) is completed; see `docs/CHANGELOG.md` and `docs/ANTARES_EPISODE_SCHEMA.md` for details.

### Rev 70 — Antares Gym Environment & Cost Reward (Phase 3)

**Goal:** Provide a stable Gym-style environment around the existing deterministic simulator and cost model so any future Antares agent (supervised or RL) can be trained and evaluated offline on historical data.

**Scope / Design Decisions:**
*   Environment focus: wrap the existing Time Machine (`SimulationDataLoader` + MPC planner) and slot-level cost logic into a thin `AntaresMPCEnv` with `reset(day)` / `step(action)` that replays historical days.
*   Reward definition: reuse the existing cost model semantics (import cost, export revenue, battery wear) to compute per-slot reward `R_t = -(cost_t - revenue_t + wear_t)` in local currency.
*   Action space (Rev 70): keep `action` as a no-op placeholder (environment follows MPC actions only), but define the hook where future revisions can inject action overrides before computing reward.
*   State vector: expose a simple, documented state vector per slot including time-of-day, prices, SoC, and basic load/PV context, derived from schedule/slot data.
*   Episodes: one environment episode corresponds to one historical day; we use the same date window and data-quality gating as the simulation episodes (`system_id="simulation"`, `data_quality_daily`).

**Implementation Steps:**
1.  Finalize `ml/simulation/env.py::AntaresMPCEnv` so that `reset(day)` builds planner inputs via `SimulationDataLoader`, generates an MPC schedule for that day, and initializes an internal pointer over the schedule slots (with timezone-safe timestamps and basic time features).
2.  Implement `_compute_reward` in `AntaresMPCEnv` based on slot-level cost (grid import, export, battery wear) using existing planner economics from config, and wire `step(action)` to advance one slot, return `(next_state, reward, done, info)` and ignore `action` for now.
3.  Document the environment contract (state vector fields, reward semantics, episode definition, and future `action` hook) in `docs/ANTARES_MODEL_CONTRACT.md` or a short new subsection so later Antares revisions can rely on it without re-reading the code.
4.  Add a small debug CLI helper (e.g. `debug/run_antares_env_episode.py`) that runs through a sample day, prints a few `(time, reward)` lines, and confirms the environment is deterministic and stable for a fixed day across runs.

**Status:** Completed (environment, reward, docs, and debug runner implemented in Rev 70).

### Rev 69 — Antares v1 Training Pipeline (Phase 3)

**Goal:** Train the first Antares v1 supervised model that imitates MPC’s per-slot decisions on validated `system_id="simulation"` data (battery + export focus) and establishes a baseline cost performance.

**Scope / Design Decisions:**
*   Targets: next-slot MPC control signals derived from simulation episodes (e.g. `battery_charge_kw`, `battery_discharge_kw`, and `export_kwh`), optionally extended later; `water_kwh` stays deterministic/context in v1.
*   Inputs: features built on top of `ml.api.get_antares_slots(dataset_version="v1")`, including time (hour-of-day, day-of-week), prices, `load_kwh`, `pv_kwh`, SoC, and recent history; days with `status="mask_battery"` are used but battery targets are ignored/zero-weighted where `battery_masked=True`.
*   Data split: use a time-based split over the July–now window (e.g. train on July–Oct `clean` + `mask_battery` days, validate on Nov+ `clean` + `mask_battery` days) with a fixed random seed and recorded date bounds so the dataset is reproducible.
*   Model family: LightGBM (or equivalent gradient-boosted trees) as the only supported model type for Rev 69; RL and neural networks are explicitly deferred to later Antares revisions in Phase 3.
*   Metrics: primary metrics are MAE/RMSE for each target plus cost-based evaluation on the validation slice by replaying predicted actions through the existing cost model (versus MPC baseline).

**Implementation Steps:**
1.  Define the exact feature/target contract for Antares v1 (Python dataclass or documented schema) based on `get_antares_slots("v1")`, including how `battery_masked` days are filtered or down-weighted per target.
2.  Create an `antares_training_runs` table in SQLite (`data/planner_learning.db`) to log each training run with: `run_id`, timestamps, dataset_version, date range, target set, model type, hyperparameters, metrics (per-target + cost-based), and artifact paths; add an optional mirror to MariaDB later.
3.  Extend `ml/train_antares.py` to: load the v1 dataset, apply the time-based train/validation split, build feature matrices/target vectors, train one LightGBM model per target (or a multi-output variant), and persist artifacts with versioned filenames (e.g. `models/antares_v1_<date>_<hash>.joblib`).
4.  Add a lightweight CLI/entrypoint (kept within `ml/train_antares.py`) that prints a concise training summary (data sizes, metrics, cost comparison vs MPC on the validation window) and records a row in `antares_training_runs`.
5.  Document the v1 model contract (inputs, targets, artifact naming, and where to load it from) in `docs/ANTARES_EPISODE_SCHEMA.md` or a new short `docs/ANTARES_MODEL_CONTRACT.md` so later Antares phases and tools can consume it without re-reading the training code.

**Status:** Completed (training pipeline, logging, and eval helper implemented in Rev 69).

**Verification Plan:**
1.  Run `python -m bin.run_planner`: record training episodes for real scheduler runs.
2.  Use the Planning Lab simulation: confirm no `training_episodes` rows appear.
3.  Monitor DB size over 24h to ensure the new table stays lightweight.

### Rev 63 — Export What-If Simulator (Lab Prototype) (ongoing/on hold)

**Goal:** Provide a deterministic, planner-consistent way to answer “what if we export X kWh at tomorrow’s price peak?” so users can see the net SEK impact before changing arbitrage settings.

**Scope:**
*   Add a debug tool (`debug/test_export_scenarios.py`) that:
    *   Uses the Learning engine’s `DeterministicSimulator` and `simulate_schedule` to re-run a **full day** (00:00–24:00) through the planner.
    *   Applies progressively stronger “export at peaks” manual plans across the highest-price slots, re-simulating the whole horizon each time.
    *   Computes full-horizon cashflow metrics (grid import cost, export revenue, battery wear) for baseline vs scenarios using the existing `_evaluate_schedule` cost model.
    *   Reports target vs realized export energy and net SEK deltas vs baseline for each scenario (prototype for Lab “Export What-If”).
*   Planner core logic stays untouched; all what-if behaviour is driven via `prepare_df` → `apply_manual_plan` → `simulate_schedule`.

**Current status:** Prototype script is in place and structurally correct, but with today’s conservative export economics most scenarios still realize ≈0 kWh of extra export (planner chooses to hold), so the tool currently acts as a “sanity check” rather than a tuner.

**Next:** Switch the simulator to use **live Nordpool + Aurora forecasts** for an arbitrary day (not just data persisted in `planner_learning.db`), and add a dedicated “relaxed economics” mode (lower cycle cost / profit margin bounds) so the Lab UI can explore truly hypothetical export behaviour without changing production guardrails.

### Rev 71 — Antares Oracle (MILP Benchmark) (Phase 3)

**Goal:** Build a deterministic “Oracle” that computes the mathematically optimal daily schedule (under perfect hindsight) so we can benchmark MPC and future Antares agents against a clear upper bound.

**Scope / Design Decisions:**
*   Use a MILP solver (e.g. PuLP with CBC in-process) to optimize a single day’s schedule given perfect historical data: prices, load, PV, battery constraints, and simple export rules.
*   Objective: minimize net energy cost (import cost + battery wear cost – export revenue) over the full day, subject to the same physical limits as the existing planner (battery capacity, charge/discharge limits, SoC bounds).
*   Inputs come from the existing Time Machine / loader: per-slot load/PV/time/price for a given day (aligned with `slot_observations` and simulation episodes).
*   Oracle is **offline only** and never used directly in production planning; it is a benchmark and training signal.

**Implementation Steps:**
1.  Implement `ml/benchmark/milp_solver.py` with a function like `solve_optimal_schedule(day)` that:
    - Loads per-slot data for `day` via `SimulationDataLoader` or directly from `slot_observations` (same local 15-min grid and prices used by MPC).
    - Builds a MILP model with decision variables for each slot: import/export, battery charge/discharge power or energy, and SoC.
    - Enforces constraints: SoC dynamics, capacity bounds, max charge/discharge power, non-negativity of flows, and any simple export constraints we already enforce in the planner.
    - Optimizes the day’s cost objective and returns a per-slot schedule (times, flows, SoC, cost components) in a DataFrame/dict structure compatible with our existing schedule schema.
2.  Add a debug entrypoint (e.g. `debug/run_oracle_vs_mpc.py`) that:
    - For a given day, runs both MPC (via `AntaresMPCEnv` / Time Machine) and the Oracle MILP.
    - Computes and prints full-day cost for each (import, export, battery wear, total) plus simple deltas and optionally a short per-hour summary.
3.  Define and document the Oracle schedule schema and cost components in `docs/ANTARES_MODEL_CONTRACT.md` (or a short `Oracle` subsection) so later Antares revisions can reuse the same format for training and evaluation.
4.  (Optional if time allows) Add a small logging hook to persist Oracle runs (per-day results) into SQLite (e.g. `oracle_daily_results`) with date, cost breakdown, and a summary of how far MPC is from the Oracle for that day.

**Status:** Completed (Oracle MILP solver, MPC comparison tool, and config wiring implemented in Rev 71).

### Rev 72 — Antares v1 Policy (First Brain) (Phase 3)

**Goal:** Train a first Antares v1 policy that leverages the Gym environment and/or Oracle signals to propose battery/export actions and evaluate them offline against MPC and the Oracle.

**Scope / Design Decisions:**
*   Start with a conservative approach: supervised or value-based learning on top of existing simulation/Oracle data before any online RL.
*   Use `AntaresMPCEnv` for rollouts and `solve_optimal_schedule(day)` as an optional “teacher” for cost-to-go or improved action labels.
*   Keep this revision offline-only: no changes to live planner control yet.

**Implementation Steps:**
1.  Define the Antares v1 policy interface and data structures (e.g. a small wrapper around the trained LightGBM models or a new model) so that given a state vector from `AntaresMPCEnv`, it can propose per-slot actions (charge/discharge/export levels).
2.  Build an offline training script (e.g. `ml/train_antares_policy.py`) that:
    - Samples episodes/days from the validated window via the Gym environment.
    - Constructs training targets either from MPC actions (imitation) or from Oracle-improved actions/cost signals where available.
    - Trains a first policy model and saves it under a versioned path (similar to Antares v1 regressors) with basic metrics.
3.  Add an evaluation helper (e.g. `ml/eval_antares_policy.py`) that:
    - Runs the learned policy in the Gym environment over a held-out set of days.
    - Computes cost vs MPC and vs Oracle (where Oracle solutions exist) and prints simple cost comparison statistics.
4.  Document the policy contract (inputs, outputs, where the model is stored, and how it will later be plugged into the scheduler) in `docs/ANTARES_MODEL_CONTRACT.md` so Phase 4 (shadow mode) can use it directly.

**Status:** Completed (offline MPC-imitating policy, training, eval, and contract implemented in Rev 72).

### Rev 73 — Antares Policy Cost Evaluation & Action Overrides (Phase 3)

**Goal:** Evaluate the Antares v1 policy in terms of full-day cost (not just action MAE) by letting it drive the Gym environment, and compare that cost against MPC and the Oracle on historical days.

**Scope / Design Decisions:**
*   Extend `AntaresMPCEnv` with a safe action-override hook so a policy can propose per-slot actions (charge/discharge/export) while still respecting battery constraints and using the existing cost model for reward.
*   Keep this revision strictly offline: the policy will only control the simulated environment, never live hardware.
*   Use both MPC and Oracle as baselines: MPC as the current production behaviour, Oracle as the theoretical lower bound.

**Implementation Steps:**
1.  Extend `AntaresMPCEnv.step(action)` so that, when an action dict is provided, it overrides MPC’s charge/discharge/export decisions for that slot (clamped to physical limits) before computing reward and updating internal state; preserve a mode where it still replays pure MPC for baseline runs.
2.  Add a cost-evaluation script (e.g. `ml/eval_antares_policy_cost.py`) that:
    - Loads the latest Antares v1 policy from `antares_policy_runs`.
    - For a configurable set of days, runs three rollouts per day: MPC-only, policy-driven, and (where available) Oracle cost from `solve_optimal_schedule(day)`.
    - Computes and prints per-day and aggregate cost statistics (import, export, wear, total) and simple deltas: `policy vs MPC`, `MPC vs Oracle`, `policy vs Oracle`.
3.  Document the action-override contract (expected action keys, clamping rules, and how the environment combines them with existing schedule context) in `docs/ANTARES_MODEL_CONTRACT.md` so future policy revisions and Phase 4 (shadow mode) can rely on the same semantics.

**Status:** Planned (next active Antares revision; will produce a cost-based policy vs MPC/Oracle benchmark).

### Rev XX - PUT THE NEXT REVISION ABOVE THIS LINE!

### Rev 74 — Tail Window Price Backfill & Final Data Sanity (Phase 3)

**Goal:** Fix and validate the recent tail of the July–now window (e.g. late November days with zero prices) so Phase 3 ends with a fully clean, production-grade dataset for both MPC and Antares training/evaluation.

**Scope / Design Decisions:**
*   Treat `slot_observations` as canonical; zero `import_price_sek_kwh` / `export_price_sek_kwh` on “normal” days are data issues, not physics.
*   Use the existing Vattenfall price backfill tools (`bin/backfill_vattenfall.py` / `bin/fix_price_gaps.py`) to repopulate missing/zero price slots over the recent window where the new recorder was not yet active.
*   Re-run the existing validation scanners and Antares cost eval tools to confirm the tail matches the rest of the window 

**Status:** Completed (tail prices backfilled via Vattenfall + fix_price_gaps; 2025-11-18 → 2025-11-27 now have realistic prices, validation scanner passes, and policy/MPC/Oracle cost evals run with finite costs on tail days).
in quality.

**Implementation Steps:**
1.  Identify all days in `data/planner_learning.db: slot_observations` where:
    - `date(slot_start)` is in the recent window (e.g. `>= 2025-11-18`), and
    - `import_price_sek_kwh` (and/or `export_price_sek_kwh`) are zero or NULL for most/all slots; list these as “price-bad” days.
2.  Configure and run the price backfill pipeline (Vattenfall API + gap fixer) over the exact range covering those days, ensuring it targets only the affected dates and updates the SQLite `slot_observations` prices in-place.
3.  Re-run:
    - `debug/validate_ha_vs_sqlite_window.py` over the tail window to confirm energy + price consistency.
    - `debug/run_policy_cost_for_day.py` and/or `ml/eval_antares_policy_cost.py` on at least one summer day (e.g. 2025-08-01) and one fixed tail day to verify MPC/policy/Oracle costs are finite and sane.
4.  Update documentation (brief note in `docs/ANTARES_EPISODE_SCHEMA.md` or `ANTARES_MODEL_CONTRACT.md`) summarising that the July–now window, including the tail, is price-complete and ready for Antares training/eval.

**Status:** Planned (final Phase 3 data-cleanup revision before Phase 4 / shadow mode).

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
