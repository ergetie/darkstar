# Project Antares: Master Plan

## 1. Executive Summary & Vision

**Vision: From Calculator to Agent.**

The current MPC planner is a sophisticated calculator: it executes a fixed set of rules based on forecasts. **Project Antares** will evolve Darkstar into a true **Energy Agent**: a self-learning system that develops an intuitive understanding of the home's energy dynamics to maximize savings and adapt to uncertainty.

This plan outlines a phased, safety-first approach to build, train, and deploy this agent, moving from offline simulation to live, graduated control.

---

## 2. Guiding Principles

These are the non-negotiable rules governing the entire project:

1.  **Safety First (The Spinal Cord):** The AI operates within the hard safety limits defined by the deterministic planner. Antares can *propose* an action, but the final execution layer will always enforce physical constraints (`min_soc_percent`, `max_charge_power_kw`, inverter limits). The AI cannot command an unsafe action.
2.  **Shadow Mode is Mandatory:** No AI model will control live hardware until it has proven its performance and safety by running in a silent "shadow mode" and consistently outperforming the existing MPC planner in simulation.
3.  **Data is the Foundation:** The quality and volume of our `antares_learning` dataset are the primary drivers of success. The data pipeline is the project's most critical asset.
4.  **Simulation-Driven Development:** All models will be trained and evaluated offline in a simulated environment (the "Time Machine") that replays historical data. We do not test new algorithms on the live system.
5.  **Explainability is a Feature:** While the AI is a "black box," we will build tools to visualize its decisions against the MPC's, providing insight into *why* it chose a different path.

---

## 3. Phased Implementation Plan

The project is divided into five distinct, sequential phases. Each phase has a clear goal and a verifiable deliverable.

### **Phase 1: The Black Box Recorder (Foundation)**

*   **Goal:** Establish the unified data pipeline necessary to train any future model. This captures the `State -> Action` relationship of the current planner.
*   **Key Tasks:**
    1.  Create the `antares_learning` table in MariaDB to serve as the central training data lake.
    2.  Implement the "Mirror" logic to dual-write training episodes to both local SQLite (for robustness) and the central MariaDB (for accessibility).
    3.  Add `system_id` to the configuration and data schema to differentiate between production and development data sources.
*   **Deliverable:** The Production Server is successfully populating the central `antares_learning` table with `system_id: "prod"` data, creating the raw material for Phase 2.
*   **Status:** **Complete.**

---

### **Phase 2: The Time Machine (Offline Simulation Environment)**

*   **Goal:** Build the "Gym" where the AI will be trained. This environment will allow us to replay history and measure the performance of any given strategy (MPC, MILP, or Antares).
*   **Key Tasks (as implemented/evolving):**
    1.  **Historical Data Foundation:**
        *   Use `slot_observations` in the local SQLite (`planner_learning.db`) as the canonical per-slot history (load, PV, import/export, SoC, prices).
        *   Populate missing days from Home Assistant using dedicated backfill tools:
            *   `bin/backfill_vattenfall.py` / `bin/fix_price_gaps.py` for prices.
            *   `bin/backfill_ha.py` / `bin/explode_rows.py` / `ml/data_activator.py` for HA sensor history, converted to 15-minute slots.
        *   Keep the live telemetry path healthy via `backend.recorder` (15-minute cumulative-delta recorder) so recent days can be replayed without extra ETL.
    2.  **Simulation & Loader:**
        *   Use `ml/simulation/data_loader.py` to build planner-ready state (prices, load, PV, SoC) from `slot_observations` for arbitrary historical days.
        *   Use `bin/run_simulation.py` as the main "Time Machine" entry point that:
            *   Iterates through a date range (e.g., `2025-07-01` to `2025-11-27`).
            *   Runs the existing planner (`planner.generate_schedule(record_training_episode=True)`) on those historical slices.
            *   Tags simulation episodes with `system_id="simulation"` so they are distinguishable from `system_id="prod"` in `antares_learning`.
    3.  **(Still to be added in later sub-phases):**
        *   A thin environment wrapper around the `DeterministicSimulator` that conforms to a Gym-like interface (`reset(day)`, `step(action)`).
        *   Formalized state/action/reward vector spaces suitable for RL agents, built on top of the same historical loader.
*   **Deliverable (Phase 2 current focus):** A robust historical replay engine (`bin/run_simulation.py` + backfill pipeline) that can generate thousands of MPC episodes from July 2025 onwards, with data quality validated against Home Assistant, forming the initial dataset for later Gym/Oracle/agent work.

---

### **Phase 3: The Gym, The Oracle, and The First Brain**

*   **Goal:** Create the complete offline training ecosystem. This involves building a standard Reinforcement Learning "Gym" environment, creating a mathematical "Oracle" to define the perfect score, and training a baseline Antares agent to imitate that perfection.
*   **Key Tasks:**
    1.  **The Gym (Environment):**
        *   Develop a class (`ml/gym/AntaresEnv.py`) that wraps the `SimulationDataLoader` and `DeterministicSimulator`. It must conform to a standard reinforcement learning interface (e.g., OpenAI Gym), with methods like:
            *   `reset(day)`: Initializes the environment with data for a specific historical day.
            *   `step(action)`: Takes an action, runs the simulation for one 15-minute slot, and returns `(next_state, reward, done, info)`.
        *   **Define the Vector Spaces:** This is where we formalize the inputs and outputs for the AI.
            *   **State ($S_t$):** A normalized vector containing: SoC (0-1), current time (cyclical features like sin/cos of hour), 48h forecast vectors (PV/Load, normalized by system capacity), 48h price vectors (normalized by daily average).
            *   **Action ($A_t$):** A discrete set of high-level commands, e.g., `[0: Charge Full, 1: Hold, 2: Discharge to cover Load, 3: Discharge to Min SoC for Export]`.
            *   **Reward ($R_{t+1}$):** A function that calculates the "score" for a single step. `Reward = (Export Revenue - Import Cost - Battery Cycle Cost)`.
    2.  **The Oracle (Benchmark):**
        *   Implement a simple MILP (Mixed-Integer Linear Programming) solver (`ml/benchmark/milp_solver.py`) using the `PuLP` library.
        *   This solver will be a function that takes a full day's worth of *perfect historical data* and calculates the mathematically optimal schedule. This defines the "100% score" for that day.
    3.  **The Training Loop:**
        *   Create the `ml/train_antares.py` script.
        *   This script will loop through historical days, use the MILP Oracle to generate the "perfect" action for each state, and store these `(State, Perfect_Action)` pairs.
        *   **Imitation Learning (First Model):** We will train a simple model (e.g., LightGBM or a small Neural Network) to predict the MILP's action given the state. This is more stable than full Reinforcement Learning for the first version.
*   **Deliverable:** A saved model file (`antares_agent_v0.1.pkl`) and a benchmark report showing the performance on 100 test days: `Rule Planner: 85% of Optimal`, `Antares v0.1: 92% of Optimal`.
*   **Status:** **Not Started. This is our next phase.**

---

### **Phase 4: The Shadow Challenger (Live Parallel Run)**

*   **Goal:** Deploy the trained agent to run silently in production, generating plans in parallel with the live MPC planner, allowing us to compare their real-world performance without risk.
*   **Key Tasks:**
    1.  **Antares Agent Service:** Create a light wrapper in `backend/` that can load the saved model and has a `.predict(state)` method.
    2.  **Scheduler Integration:** Modify `backend/scheduler.py`. After the main planner runs, it will call the Antares agent with the same `input_data`.
    3.  **Shadow Storage:** The agent's proposed schedule will be saved to a new table `antares_plan_history` in MariaDB.
    4.  **The Scorekeeper UI:** Build a new component in the frontend that queries both `plan_history` (MPC) and `antares_plan_history` (AI) and displays a daily/weekly cost comparison chart.
*   **Deliverable:** A live dashboard in the Darkstar UI showing a bar chart: "Yesterday's Cost: MPC vs. Antares".

---

### **Phase 5: The Gatekeeper (Graduated Control)**

*   **Goal:** Allow Antares to take control of the live system once it has proven its superiority and safety.
*   **Key Tasks:**
    1.  **The Gatekeeper Logic:** Implement a final validation step in the scheduler.
        *   `plan_mpc = run_mpc()`
        *   `plan_antares = run_antares()`
        *   `if is_safe(plan_antares) and cost(plan_antares) < cost(plan_mpc): execute(plan_antares)`
        *   `else: execute(plan_mpc)`
    2.  **Graduated Control:** The `execute` logic will be controlled by a new config setting:
        ```yaml
        antares:
          control_mode: 'shadow'  # [shadow, export_only, full_control]
        ```
        *   `export_only`: Antares decisions are only used for the `export_kw` column, the rest is from MPC.
        *   `full_control`: Antares controls `charge_kw`, `export_kw`, etc.
*   **Deliverable:** The system runs autonomously, with the UI showing which agent made the decision for each day, and Antares demonstrably saving money over the MPC.
