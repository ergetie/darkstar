# Kepler Vision: The Intelligent Energy Agent

This document describes the long-term vision where **Kepler (MILP)** becomes the primary planner for Darkstar, driven by the **Aurora Intelligence Suite**.

## The Aurora Architecture

"Aurora" is the umbrella term for the intelligent components of Darkstar:

1.  **Aurora Vision** (formerly Forecasting): The "Eyes".
    *   Predicts the future (Load, PV, Prices) using LightGBM.
2.  **Aurora Strategy** (formerly Strategy Engine): The "Brain".
    *   Makes high-level decisions (Risk tolerance, S-Index, Target SoC) based on context.
3.  **Aurora Reflex** (formerly Learning Engine): The "Inner Ear".
    *   Maintains balance by tuning the other components based on feedback (Short-term bias & Long-term drift).

The core loop is:

> **Aurora Vision** → **Aurora Strategy** → **Kepler (Planner)** → **Execute** → **Aurora Reflex**

---

## 1. Why Kepler (MILP)?

Darkstar’s end goal is not “fancy RL” but **reliable, intelligent energy management** that:

- Minimises total cost over long horizons.
- Respects comfort and hardware constraints.
- Is explainable to humans, and debuggable in production.

**Kepler (MILP)** is the perfect engine because:

- It expresses **physics + constraints exactly**:
  - Battery SoC limits, power limits, water-heater quotas, export caps, etc.
- It is **transparent and deterministic**:
  - Same inputs → same plan; easy to reason about and regression-test.
- It plays beautifully with **forecasts**:
  - Aurora Vision gives us best-guess futures; Kepler computes the best response.
- It can be **parameterised by “policy knobs”**:
  - We can embed comfort vs cost trade-offs via weights and constraints that Aurora Strategy can learn over time.

RL remains valuable, but as a **Strategy Engine**:
- It helps discover good policies and test cost models.
- It learns mappings from context → Kepler parameters.
- It is not required to emit kW directly to achieve “intelligence”.

---

## 2. High-Level Architecture

1. **Aurora Reflex (Learning & Metrics)**
   - Consolidated metrics from `slot_observations`, forecasts, and schedules.
2. **Aurora Vision (Forecasting)**
   - Load/PV forecasts with uncertainty.
3. **Aurora Strategy (Policy)**
   - Chooses policy parameters (`θ`) for Kepler based on context (Weather, Risk, Prices).
4. **Kepler Planner**
   - Given forecasts, tariffs and policy parameters (`θ`), solves for a cost-optimal schedule over 24–48h.
5. **Evaluation & Feedback**
   - Compares realised outcomes vs expectations; Aurora Reflex updates metrics and feeds model training.

Conceptually:

```text
Historical data ──► Aurora Reflex ──► Aurora Vision (forecasts)
                         ▲                     │
                         │                     ▼
                   Metrics & runs       Aurora Strategy (RL/Policy)
                         │                     │
                         ▼                     ▼
                   Policy learner       Kepler Planner (MILP)
                         │                     │
                         └────► Feedback ◄─────┘
```

---

## 3. Kepler Problem Definition

### 3.1 Horizon and Time Resolution

- Horizon: typically 24–48 hours.
- Resolution: 15-minute slots.
- Objective: minimise **total cost** over the horizon.

### 3.2 Decision Variables

Per slot `t`:

- `charge_t` (kWh): battery charge energy.
- `discharge_t` (kWh): battery discharge energy.
- `grid_import_t` (kWh): import from grid.
- `grid_export_t` (kWh): export to grid.
- `soc_t` (kWh): battery state of charge.
- `water_grid_t` / `water_pv_t`: optional water-heater allocation.

### 3.3 Constraints

- **Energy balance per slot**: `load + charge + export = pv + discharge + import`.
- **Battery dynamics**: `soc_{t+1} = soc_t + charge_t − discharge_t`.
- **Water heating**: Daily quota met.
- **Export / import limits**: Inverter / grid constraints.

### 3.4 Objective Function

```text
minimise  Σ_t (grid_import_t * import_price_t
               − grid_export_t * export_price_t
               + wear_cost * (charge_t + discharge_t)
               + ramping_cost * |charge_t - charge_{t-1}|)
         + comfort_terms
```

**Ramping Cost**: A key addition to prevent "sawtooth" behavior.

---

## 4. Integration with Aurora Vision

Kepler is only as good as its inputs. Aurora Vision becomes the default world model:

- **Forecast inputs per slot:** `load`, `pv`.
- **Uncertainty:**
  - Aurora Vision provides uncertainty measures (p10/p50/p90).
  - Aurora Strategy uses this to adjust Kepler's safety margins (e.g. `min_soc`).

---

## 5. Aurora Strategy: The "Brain"

To get a self-learning system without relying on RL for raw control, we use Aurora Strategy to tune **Kepler policy parameters (`θ`)**:

- `θ_soc_reserve_peak`: minimum SoC during defined peak windows.
- `θ_export_threshold`: minimum price spread vs future to export aggressively.
- `θ_wear_cost`: effective wear cost per kWh cycled.
- `θ_ramping_cost`: penalty for rapid power changes.

**Online Adaptation:**
- **Aurora Strategy**: Reads current context (Aurora Vision forecasts, tariffs, weather). Queries a policy model to choose `θ_today`.
- **Kepler**: Uses `θ_today` to build and solve the optimisation.

---

## 6. Roadmap

### Phase 1: Foundation (Completed)
- [x] **Kepler Core**: Rename Oracle to Kepler, fix sawtooth (ramping), integrate as default planner.
- [x] **Strategic S-Index**: Decouple safety (load inflation) from strategy (target SoC).
- [x] **Basic Strategy**: `StrategyEngine` class that handles Vacation Mode and basic Weather Volatility.

### Phase 2: Aurora Strategy (Next)
- [x] **Dynamic Parameters (K5)**:
    - Wire `wear_cost`, `ramping_cost`, and `export_threshold` to be dynamically tunable per-plan.
    - Allow Strategy Engine to override these based on context (e.g., "Aggressive Export" mode).
- [x] **Context Awareness**:
    - Ingest Price Trends (e.g., "Price Plunge coming in 3 days") to adjust long-term buffers.
    - [x] **Grid Constraints** (K8): "Grid Peak Shaving" requirements.

### Phase 3: Aurora Reflex (The Learning Loop)
- [x] **K6: The Learning Engine** (Plan vs Actuals)
- [x] **K7: The Mirror** (Backfill & Visualization)
- [ ] **Feedback Loops**:
    - [x] **Short-term** (K9): Feed recent errors back to Aurora Vision (Analyst & Auto-Tuner).
    - [x] **Long-term** (Aurora Reflex): Auto-tune physical constants based on historical drift.
        - **A. Efficiency**: Skipped (Ambiguous signal).
        - [x] **B. Safety Margin**: Tune `s_index.base_factor` (Lifestyle Creep).
        - [x] **C. Confidence**: Tune `forecasting.pv_confidence_percent` (Dirty Panels).
        - [x] **D. Virtual Cost**: Tune `battery_economics.battery_cycle_cost_kwh` (ROI Calibration).
        - [x] **E. Capacity**: Tune `battery.capacity_kwh` (Capacity Fade).

### Phase 4: Full Autonomy ("Agent Mode")
- [ ] **Policy Learning**:
    - Replace heuristic `if/else` rules in Aurora Strategy with a learned policy or advanced lookups.
- [ ] **Risk Agent**:
    - Autonomous management of risk appetite (e.g., "High Risk" strategy when savings potential is huge).
