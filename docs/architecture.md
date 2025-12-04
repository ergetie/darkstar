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

## 3. Strategic S-Index (Decoupled)
To manage risk without "Double Buffering", we decoupled the strategy:

1.  **Load Inflation (Intra-day Safety)**:
    *   **Goal**: Buffer against *today's* forecast errors.
    *   **Mechanism**: Static Multiplier (e.g., `1.1x`).
    *   **Effect**: Planner assumes load is 10% higher than forecast.

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
*   **Mechanism**: LightGBM models predict Load and PV generation.
*   **Uncertainty**: Provides p10/p50/p90 confidence intervals.

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

## 5. Data Flow
1.  **Inputs**: Nordpool Prices, Weather Forecasts, Home Assistant Sensors.
2.  **Aurora**: Generates/Corrects Forecasts.
3.  **Planner (Pass 0)**: Applies S-Index (Safety Margins) & Calculates Terminal Value.
4.  **Planner (Pass 1-4)**: Identifies windows, schedules water heating.
5.  **Adapter**: Converts Planner Data -> Kepler Input.
6.  **Kepler Solver**: Solves for Optimal Schedule.
7.  **Output**: `schedule.json` (consumed by UI and Home Assistant).
