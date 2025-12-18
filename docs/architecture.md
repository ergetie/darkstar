# Darkstar Architecture Documentation

## 1. System Overview
Darkstar is an intelligent energy management system designed to optimize residential energy usage. It uses a **Model Predictive Control (MPC)** approach, combining machine learning forecasts (Aurora) with a Mixed-Integer Linear Programming (MILP) solver (Kepler).

### Core Philosophy
*   **Maximize Value**: Buy low, sell high, and use energy efficiently.
*   **Robustness**: Plan for the worst (High Load/Low PV) using the **S-Index**.
*   **Strategic**: Look ahead (D2+) to make decisions today (Terminal Value).

---

## 2. The Kepler Solver (MILP)
Kepler is the decision-making core. It solves an optimization problem to generate the optimal charge/discharge schedule.

### Objective Function
The solver minimizes the total cost over the planning horizon (typically 24-48 hours):
```
Minimize: Sum(Import_Cost - Export_Revenue + Wear_Cost) - (End_SoC * Terminal_Value)
```

### Key Concepts
*   **Hard Constraints**: Physics limits (Battery Capacity, Inverter Power), Energy Balance.
*   **Soft Constraints**: Terminal Value (Incentivizes ending with charge).
*   **Inflated Demand**: The solver sees a "Safety Margin" inflated load (via S-Index) as hard demand it *must* meet.

---

## 3.  **Strategic S-Index (Decoupled)**:
    To manage risk without "Double Buffering", we decoupled the strategy:

    1.  **Risk Appetite (Sigma Scaling)**:
        *   **Goal**: Buffer against *today's* forecast errors (Uncertainty).
        *   **Mechanism**: User-tunable Sigma Scaling (1-5 Scale).
        *   **Formula**: `Safety Margin = Uncertainty * Sigma(RiskAppetite)`.
        *   **Effect**:
            *   Safety (1): Covers p90 (Worst Case).
            *   Neutral (3): Covers p50 (Mean).
            *   Gambler (5): Covers p25 (Under-provisioning).

    2.  **Dynamic Target SoC (Inter-day Strategy)**:
        *   **Goal**: Prepare for *tomorrow's* risk (Cold/Cloudy D2).
        *   **Mechanism**: Hard Constraint on End-of-Day SoC.
        *   **Formula**: `Target % = Min % + (Risk_Factor - 1.0) * Scaling`.
        *   **Effect**: If D2 is risky, we hold a larger buffer (e.g., 30%). If D2 is safe, we hold `Min %`.

    This ensures we don't inflate today's load just because tomorrow is cold (which caused excessive battery usage in the plan).
---

## 4. Aurora Intelligence Suite
Darkstar's intelligence is powered by the **Aurora Suite**, which consists of three pillars:

### 4.1 Aurora Vision (The Eyes)
*   **Role**: Forecasting.
*   **Mechanism**: LightGBM models predict Load and PV generation with 11 features (time, weather, context).
*   **Uncertainty**: Provides p10/p50/p90 confidence intervals for probabilistic S-Index.
*   **Extended Horizon**: Aurora forecasts 168 hours (7 days), enabling S-Index to use probabilistic bands for D+1 to D+4 even when price data only covers 48 hours.
*   **Config**: `s_index.s_index_horizon_days` (integer, default 4) controls how many future days are considered.

### 4.2 Aurora Strategy (The Brain)
*   **Role**: Decision Making.
*   **Mechanism**: Determines high-level policy parameters (`θ`) for Kepler based on context (Weather, Risk, Prices).
*   **Outputs**: Target SoC, Export Thresholds, Risk Appetite.

### 4.3 Aurora Reflex (The Inner Ear)
*   **Role**: Learning & Balance.
*   **Mechanism**: Long-term feedback loop that auto-tunes physical constants and policy weights based on historical drift.
*   **Analyzers**:
    *   **Safety**: Tunes `s_index.base_factor` (Lifestyle Creep).
    *   **Confidence**: Tunes `forecasting.pv_confidence_percent` (Dirty Panels).
    *   **ROI**: Tunes `battery_economics.battery_cycle_cost_kwh` (Virtual Cost).
    *   **Capacity**: Tunes `battery.capacity_kwh` (Capacity Fade).

---

## 5. Modular Planner Pipeline

The planner has been refactored from a monolithic "God class" into a modular `planner/` package:

```
planner/
├── pipeline.py           # Main orchestrator (PlannerPipeline)
├── inputs/               # Input Layer
│   ├── data_prep.py      # prepare_df(), apply_safety_margins()
│   ├── learning.py       # Aurora overlay loading
│   └── weather.py        # Temperature forecast fetching
├── strategy/             # Strategy Layer
│   ├── s_index.py        # S-Index calculation (dynamic risk factor)
│   ├── windows.py        # Cheap window identification
│   └── manual_plan.py    # Manual override application
├── scheduling/           # Pre-solver Scheduling
│   └── water_heating.py  # Water heater window selection
├── solver/               # Kepler MILP Integration
│   ├── kepler.py         # KeplerSolver (MILP optimization)
│   └── adapter.py        # DataFrame ↔ Kepler types conversion
└── output/               # Output Layer
    ├── schedule.py       # schedule.json generation
    ├── soc_target.py     # Per-slot soc_target_percent calculation
    └── formatter.py      # DataFrame → JSON formatting
```

### Data Flow

```mermaid
flowchart LR
    A[Inputs<br/>Prices, Forecasts, HA State] --> B[Data Prep<br/>+ Safety Margins]
    B --> C[Strategy<br/>S-Index, Target SoC]
    C --> D[Scheduling<br/>Water Heating]
    D --> E[Kepler Solver<br/>MILP Optimization]
    E --> F[SoC Target<br/>Per-slot targets]
    F --> G[Output<br/>schedule.json]
```

1. **Inputs**: Nordpool Prices, Weather Forecasts, Home Assistant Sensors.
2. **Data Prep**: `prepare_df()` + `apply_safety_margins()` (S-Index inflation).
3. **Strategy**: Calculate S-Index, Terminal Value, Dynamic Target SoC.
4. **Scheduling**: Schedule water heating into cheap windows.
5. **Kepler Solver**: MILP optimization for optimal charge/discharge schedule.
6. **SoC Target**: Apply per-slot `soc_target_percent` based on action type:
   - Charge blocks → Projected SoC at block end
   - Export blocks → Projected SoC at block end (with guard floor)
   - Hold → Entry SoC (current battery state)
   - Discharge → Minimum SoC
7. **Output**: `schedule.json` consumed by UI and Home Assistant automation.

### Key Entry Point

```python
from planner.pipeline import PlannerPipeline, generate_schedule

# Production usage
pipeline = PlannerPipeline(config)
schedule_df = pipeline.generate_schedule(input_data, mode="full")
```

**Legacy Reference**: The original 3,600-line heuristic planner is archived at `archive/legacy_mpc.py` with documentation in `docs/LEGACY_MPC.md`.
