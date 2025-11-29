# Darkstar Energy Manager: Master Plan

**Vision: From Calculator to Agent**
Darkstar is transitioning from a deterministic optimizer (v1) to an intelligent energy agent (v2). It does not just optimize based on static config; it observes context (Weather, Vacation, Prices), predicts outcomes (Aurora ML), and actively strategizes (Strategy Engine) to maximize efficiency and comfort.

---

## Active Revisions

### Rev 81 — Antares RL v1.1 (Horizon-Aware State + Terminal SoC Shaping)

**Goal:** Move RL from locally price-aware to day-aware so it charges enough before known evening peaks and avoids running empty too early, while staying within the existing AntaresMPCEnv cost model.

**Scope / Design Decisions:**
*   Extend the RL state with simple horizon features (time-to-end-of-day and a short-horizon peak-price indicator) so the policy can “see” that high prices are coming later.
*   Add a small terminal SoC shaping term so the agent is nudged to end the day with SoC close to the starting level (Oracle-style), discouraging both “empty too early” and “full with no peaks left.”
*   Keep the core per-slot cost (import − export + wear) and MPC/Oracle behaviour unchanged; only the RL contract and reward shaping are updated.

**Implementation Steps:**
1.  Extend `AntaresMPCEnv` state vector to include:
    - `hours_until_end_of_day` for each slot, based on the schedule window.
    - `max_import_price_next_12h` (rolling max of import price over the next ~12h of slots), computed once per day in `reset()` and exposed via `_build_state_vector`.
2.  Update `AntaresRLEnv` / training wrapper so the observation space reflects the new 8-D state and bump the logged `state_version` for new RL runs (v1.1).
3.  Add terminal SoC shaping in `AntaresRLEnv.step()`:
    - When an episode ends, apply a small penalty proportional to `|final_soc_percent − initial_soc_percent|` so the policy is biased towards ending the day near its starting SoC, Oracle-style.
4.  Retrain the RL agent with the updated contract (1–2M timesteps), then re-run:
    - `ml/eval_antares_rl_cost.py --days 10`
    - `debug/inspect_mpc_rl_oracle_stats.py --day YYYY-MM-DD`
    - `debug/plot_day_mpc_rl_oracle.py --day YYYY-MM-DD`
    to verify that RL holds more energy for evening peaks and stays closer to MPC/Oracle timing.

**Status:** In progress (state and shaping changes wired in; next step is to retrain RL v1.1 and compare cost/behaviour vs the Rev 80 baseline).

### Rev 80 — RL Price-Aware Gating (Phase 4/5)

**Goal:** Make the v1 Antares RL agent behave economically sane per-slot (no discharging in cheap hours, prefer charging when prices are low, prefer discharging when prices are high), while keeping the core cost model and Oracle/MPC behaviour unchanged.

**Scope / Design Decisions:**
*   Implement price-aware action gating inside `AntaresMPCEnv` so any RL-controlled episode automatically prefers charge vs discharge based on the day's own import price distribution.
*   Keep this gating completely transparent to MPC and Oracle (they do not use the RL override path), and keep evaluation cost definition unchanged.
*   Expose simple text diagnostics so we can quickly see how often MPC/RL/Oracle charge or discharge in cheap vs expensive slots for a given day.

**Implementation Steps:**
1.  Extend `AntaresMPCEnv.reset()` to precompute per-day import price quantiles (`q25`, `q50`, `q75`) from the generated MPC schedule (ignoring zero prices) and store them on the environment instance.
2.  Update `AntaresMPCEnv.step()` RL override path so that when both `battery_charge_kw` and `battery_discharge_kw` are requested:
    - In cheap slots (price ≤ `q25`), always prefer pure charging (set discharge to 0).
    - In expensive slots (price ≥ `q75`), always prefer pure discharging (set charge to 0).
    - In mid-price slots, keep the existing magnitude-based tie-breaker, but never allow pure discharge in clearly cheap slots.
3.  Add a small debug helper `debug/inspect_mpc_rl_oracle_stats.py` that:
    - For a given `--day`, runs a 24h MPC episode, an RL episode, and loads the Oracle schedule.
    - Prints compact stats showing, for each of MPC/RL/Oracle, how many slots are net-charging vs net-discharging and their mean price/net power in those slots.

**Status:** Completed (price-aware gating wired into `AntaresMPCEnv` RL overrides, MPC/Oracle behaviour unchanged, and `debug/inspect_mpc_rl_oracle_stats.py` available to quickly compare MPC/RL/Oracle charge/discharge patterns against the day’s price distribution).

**Operational Notes / Retrain Sequence (RL v1 with gating):**
*   Training (rough pass, ~1M timesteps) – from project root:
    - `PYTHONPATH=. ./venv/bin/python ml/train_antares_rl.py --timesteps 1_000_000`
*   Evaluation on recent tail days (uses latest `antares_rl_runs` entry):
    - `PYTHONPATH=. ./venv/bin/python ml/eval_antares_rl_cost.py --days 10`
*   Per-day behavioural check (MPC/RL/Oracle stats + graph), e.g. for 2025-11-20:
    - `PYTHONPATH=. ./venv/bin/python debug/inspect_mpc_rl_oracle_stats.py --day 2025-11-20`
    - `PYTHONPATH=. ./venv/bin/python debug/plot_day_mpc_rl_oracle.py --day 2025-11-20`
*   If the 1M run looks promising but still noisy, run a deeper pass:
    - `PYTHONPATH=. ./venv/bin/python ml/train_antares_rl.py --timesteps 2_000_000`
    - Repeat the evaluation + per-day checks with the new latest run.

### Rev 79 — RL Visual Diagnostics (MPC vs RL vs Oracle)

**Goal:** Provide a simple, repeatable way to visually compare MPC, RL, and Oracle behaviour for a single day (battery power, SoC, prices, export) in one PNG image so humans can quickly judge whether the RL agent is behaving sensibly relative to MPC and the Oracle.

**Scope / Design Decisions:**
*   Use a CLI script that generates a single multi-panel PNG (MPC, RL, Oracle stacked) using Matplotlib and then opens it in the default image viewer, avoiding any new UI or frontend work.
*   Reuse the existing environment and Oracle code paths to ensure the plotted schedules are exactly those used for cost evaluation.

**Implementation Steps:**
1.  Add a debug script (e.g. `debug/plot_day_mpc_rl_oracle.py`) that for a given `--day YYYY-MM-DD`:
    - Builds the MPC schedule by running `AntaresMPCEnv` with no overrides and extracting per-slot `start_time`, price, battery charge/discharge, SoC, and export.
    - Builds the RL schedule by running `AntaresMPCEnv` with the latest RL policy from `antares_rl_runs` (via `AntaresRLPolicyV1`) and recording the per-slot RL actions and resulting SoC.
    - Builds the Oracle schedule for the same day via `solve_optimal_schedule(day)` and converts its kWh decisions to kW and SoC%.
2.  Plot all three schedules into one PNG:
    - Three stacked panels (MPC, RL, Oracle) sharing the same time axis.
    - Each panel shows: price, net battery power (charge−discharge), SoC%, and export kW, with fixed y-axis ranges across panels for each quantity.
    - Save the PNG to `debug/plots/mpc_rl_oracle_<YYYY-MM-DD>.png`.
3.  After saving, attempt to open the PNG with the default image viewer (e.g. using `xdg-open` on Linux); ignore failures so the script still completes in headless environments.

**Status:** Completed (CLI script `debug/plot_day_mpc_rl_oracle.py` added; generates and opens a multi-panel PNG comparing MPC vs RL vs Oracle for a chosen day using the same schedules used in cost evaluation).

### Rev 78 — Tail Zero-Price Repair (Phase 3/4)

**Goal:** Ensure the recent tail of the historical window (including November 2025) has no bogus zero import prices on otherwise normal days, so MPC/RL/Oracle cost evaluations are trustworthy.

**Scope / Design Decisions:**
*   Treat mixed zero/non-zero prices within the same day as a data-quality issue, not a physical reality; Vattenfall spot prices are never actually zero for these slots.
*   Repair only days where some slots have `import_price_sek_kwh = 0.0` and others have non-zero prices; leave fully empty/zero days untouched for separate inspection.

**Implementation Steps:**
1.  Add `debug/fix_zero_price_slots.py` that:
    - Scans `slot_observations` for days where `import_price_sek_kwh` is zero for some slots and non-zero for others.
    - For those days, treats zero prices as missing and forward/back-fills them from neighbouring non-zero prices within the same day.
    - Leaves entire days with all-zero prices unchanged so they remain obvious for manual analysis.
2.  Run the repair tool on the tail window (e.g. mid-November onward) and re-check:
    - `MIN(import_price_sek_kwh) > 0` and zero-count = 0 for all affected days.
    - RL/MPC/Oracle cost evaluations on these days now behave numerically sensibly (no “free energy” exploits).

**Status:** Completed (zero-price slots repaired via `debug/fix_zero_price_slots.py`; tail days such as 2025-11-18 → 2025-11-27 now have realistic 15-minute prices with no zeros, and cost evaluations over this window are trusted).

### Rev 77 — Antares RL Diagnostics & Reward Shaping (Phase 4/5)

**Goal:** Add tooling and light reward shaping so we can understand what the RL agent is actually doing per slot and discourage clearly uneconomic behaviour (e.g. unnecessary discharging in cheap hours), without changing the core cost definition used for evaluation.

**Scope / Design Decisions:**
*   Keep the evaluation cost (import − export + wear) unchanged; use shaping only as a learning aid.
*   Focus on diagnostics first (per-slot traces and graphs), then introduce minimal shaping (price-aware discharge penalty) to steer PPO away from obviously bad patterns.

**Implementation Steps:**
1.  Add `debug/run_rl_policy_for_day.py`:
    - For a given `--day`, runs the latest RL policy through `AntaresMPCEnv` and logs per-slot:
        - Start time, prices, MPC vs RL charge/discharge/export, and per-slot RL cost.
    - Prints first/last slots and the total RL cost for the day as a quick sanity check.
2.  Extend `ml/rl/antares_env.py` with:
    - State/reward sanitisation (NaN/inf guards) so PPO never sees invalid values.
    - A simple per-day “cheap price” threshold (80% of the median non-zero import price) and a small penalty for discharging below that threshold, used only for RL training reward shaping.
3.  Document the RL reward-shaping contract in `docs/ANTARES_MODEL_CONTRACT.md` so future revisions know exactly what extra penalties are active during training.

**Status:** Completed (diagnostic tools and mild price-aware discharge penalty added; RL evaluation still uses the unshaped cost function, and the latest PPO v1 baseline is ~+8% cost vs MPC over recent tail days with Oracle as the clear lower bound).

### Rev 76 — Antares RL Agent v1 (Phase 4/5)

**Goal:** Design, train, and wire up the first real Antares RL agent (actor–critic NN) that uses the existing AntaresMPCEnv, cost model, and shadow plumbing, so we can evaluate a genuine learning-based policy in parallel with MPC and Oracle on historical data and (via shadow mode) on live production days.

**Scope / Design Decisions:**
*   Use the current `AntaresMPCEnv` state and reward as the RL contract: state = (time, load/pv, SoC, prices, etc.), action = continuous battery charge/discharge/export power; reward = negative cost (import – export + wear + penalties).
*   Introduce a single, well-supported RL stack (PyTorch + PPO/SAC-style algorithm) and keep the model small (MLP) but production-ready (versioned artefacts, run metadata, deterministic seeds where practical).
*   Reuse existing data-quality guards (`data_quality_daily`) and episode filters so the RL agent only trains and evaluates on `clean`/`mask_battery` days, and uses the same cost metrics as Phase 3 for comparison vs MPC/Oracle.

**Implementation Steps:**
1.  RL formulation + contracts:
    - Add a short Phase 4/5 RL section to `docs/ANTARES_MODEL_CONTRACT.md` that freezes:
        - State vector layout (starting from `AntaresMPCEnv` state) and any extra features (e.g. day-of-week, month).
        - Action space (continuous `[charge_kw, discharge_kw, export_kw]` with bounds) and how clamping is applied.
        - Reward definition (slot cost + wear + constraint penalties) and episode termination (per-day).
    - Ensure this contract is clearly marked as v1 so future changes can be versioned.
2.  RL dependencies and scaffolding:
    - Add PyTorch (and, if needed, a minimal RL helper library) to the Python environment via `requirements.txt` / `pyproject.toml`, matching project style.
    - Implement a light-weight Gym-style wrapper around `AntaresMPCEnv` (e.g. `ml/rl/antares_env.py`) exposing `reset()` / `step(action)` with `numpy` states and rewards, and handling date selection from the `clean`/`mask_battery` day list.
3.  RL training pipeline:
    - Create `ml/train_antares_rl.py` that:
        - Builds train/validation day splits over the July–now `clean`/`mask_battery` window (e.g. time-based split).
        - Trains an actor–critic RL agent (PPO/SAC-style) on the train days, with configurable hyperparameters and seeds.
        - Logs each run into a new SQLite table (e.g. `antares_rl_runs`) with: `run_id`, algo, model_version, hyperparams, train/val windows, core metrics (average reward, cost, SoC/water violations), and artefact path.
        - Saves model weights and normalisation stats under `ml/models/antares_rl_v1/<timestamp_runid>/`.
4.  RL policy wrapper + shadow integration:
    - Implement `AntaresRLPolicyV1` (e.g. `ml/policy/antares_rl_policy.py`) that:
        - Loads a chosen `antares_rl_runs` entry and its weights from the artefact directory.
        - Exposes `.predict(state)` returning an action dict compatible with the existing override path (`battery_charge_kw`, `battery_discharge_kw`, `export_kw`).
    - Extend the shadow runner (`ml/policy/shadow_runner.py`) and planner hook so that:
        - We can select which policy to use in shadow mode (`lightgbm` vs `rl`) via config (e.g. `antares.shadow_policy_type`).
        - Shadow schedules produced by the RL policy are written to `antares_plan_history` with the RL `run_id` and a distinct `system_id` suffix (e.g. `prod_shadow_rl_v1`).
5.  RL evaluation and comparison:
    - Add `ml/eval_antares_rl_cost.py` (or extend existing eval scripts) to:
        - Run the RL policy over a validation window of historical days in `AntaresMPCEnv`, computing MPC vs RL vs Oracle cost per day and in aggregate.
        - Report safety-related metrics (SoC limit breaches, unmet water heating) for RL vs MPC.
    - Update `debug/compare_shadow_vs_mpc.py` (if needed) so it can explicitly reference RL runs (e.g. filter by `system_id` suffix) when comparing MPC vs Antares on production-shadow days.
6.  Verification and documentation:
    - Run RL training for at least one v1 configuration, then:
        - Evaluate on a held-out historical window and confirm results are numerically sane (even if not yet better than MPC).
        - Enable RL shadow mode in a dev/QA environment (config change only) and confirm `antares_plan_history` starts collecting RL-based shadow plans without affecting HA.
    - Document in `docs/PLAN.md` and `docs/ANTARES_MODEL_CONTRACT.md` which RL run/version is considered the current v1 baseline for Phase 4/5, and how to retrain/evaluate it.

**Status:** Completed (RL v1 agent scaffolded with PPO, RL runs logged to `antares_rl_runs`, models stored under `ml/models/antares_rl_v1/...`, evaluation script `ml/eval_antares_rl_cost.py` in place; latest RL baseline run is ~+8% cost vs MPC over recent tail days with Oracle as clear best, ready for further tuning in Rev 77+).

### Rev 75 — Antares Shadow Challenger v1 (Phase 4)

**Goal:** Run the latest Antares policy in shadow mode alongside the live MPC planner, persist daily shadow schedules with costs, and provide basic tooling to compare MPC vs Antares on real production data (no hardware control yet).

**Scope / Design Decisions:**
*   Integrate Antares only after the existing planner has produced its normal schedule; the shadow path must be read-only and never influence Home Assistant switches in Phase 4.
*   Use the existing Antares policy contract (`AntaresPolicyV1`, environment state, and cost model) without inventing a new control surface; keep Phase 4 focused on evaluation, not new policy logic.
*   Store shadow plans in MariaDB as first-class history (`antares_plan_history`), keyed so we can join later to `slot_observations`, `antares_learning` / `training_episodes`, and live MPC schedule history.

**Implementation Steps:**
1.  Backend integration hook:
    - Identify the canonical point where the MPC schedule is finalized (likely `backend/scheduler.py` or the strategy engine) and add a shadow-mode hook that:
        - Builds the same `input_data` / context object Antares used in simulation (prices, forecasts, config).
        - Calls an Antares runner (e.g. `ml/policy/antares_policy.py` + `AntaresMPCEnv` wrapper) to generate a full-day shadow schedule using the latest `AntaresPolicyV1` artefacts recorded in `antares_policy_runs`.
        - Never writes to HA; the shadow schedule exists only in memory and DB.
2.  Persistence schema and writer:
    - Define a MariaDB table (e.g. `antares_plan_history`) with at least:
        - Keys: `id`, `system_id`, `plan_date`, `episode_start_local`, `policy_run_id`, `created_at`.
        - Payload: `shadow_schedule_json` (slot list with timestamps and flows/actions), `metrics_json` (summary costs, constraints, notes).
    - Implement a small writer component that:
        - Serializes the shadow schedule and cost summary into JSON.
        - Inserts one row per day into `antares_plan_history` from the backend hook.
        - Uses `system_id` to distinguish `prod_shadow_v1` from future variants.
3.  Cost comparison tooling:
    - Add a CLI/debug tool (e.g. `debug/compare_shadow_vs_mpc.py`) that for a given date range:
        - Reads live MPC schedules and the matching Antares shadow schedules from DB.
        - Joins both to realized `slot_observations` (flows + prices) for those dates.
        - Recomputes daily cost for MPC and Antares using the same cost model as Phase 3 and prints per-day and aggregate comparisons.
4.  Validation and safety checks:
    - Verify on a small window (e.g. 3–5 days) that:
        - Shadow schedules are generated every time the planner runs and persisted correctly.
        - The cost report script produces finite, sensible MPC vs Antares costs on production data.
    - Document the shadow-mode contract (where it hooks in, what is stored, and how to read it) briefly in `docs/ANTARES_MODEL_CONTRACT.md` or a short Phase 4 section.

**Status:** Planned (first Phase 4 revision; enables production shadow runs and MPC vs Antares cost comparison on real data).

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
