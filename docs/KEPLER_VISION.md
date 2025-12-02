# Kepler Vision: The Intelligent Energy Agent

This document describes the long-term vision where **Kepler (MILP)** becomes the primary planner for Darkstar, tightly integrated with:

- **Aurora** (LightGBM forecasting) for prices, load and PV.
- The **Strategy Engine** (RL/Policy) for context-aware policy decisions.
- The **Learning Engine** for metrics, experimentation and tuning.

The core loop is:

> **Forecast (Aurora)** → **Strategize (Strategy Engine)** → **Plan (Kepler)** → **Execute** → **Learn**

The aim is to get a **smart, self-learning system** with:

- Deterministic, auditable schedules.
- Clear comfort and safety guarantees.
- Automatic tuning over months of data.

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
  - Aurora gives us best-guess futures; Kepler computes the best response.
- It can be **parameterised by “policy knobs”**:
  - We can embed comfort vs cost trade-offs via weights and constraints that the Strategy Engine can learn over time.

RL remains valuable, but as a **Strategy Engine**:
- It helps discover good policies and test cost models.
- It learns mappings from context → Kepler parameters.
- It is not required to emit kW directly to achieve “intelligence”.

---

## 2. High-Level Architecture

1. **Data & Metrics (Learning Engine)**
   - Consolidated metrics from `slot_observations`, forecasts, and schedules.
2. **Aurora Forecasting**
   - Load/PV forecasts with uncertainty.
3. **Strategy Engine + Policy Learner**
   - Chooses policy parameters (`θ`) for Kepler based on context (Weather, Risk, Prices).
4. **Kepler Planner**
   - Given forecasts, tariffs and policy parameters (`θ`), solves for a cost-optimal schedule over 24–48h.
5. **Evaluation & Feedback**
   - Compares realised outcomes vs expectations; Learning Engine updates metrics and feeds model training.

Conceptually:

```text
Historical data ──► Learning Engine ──► Aurora (forecasts)
                         ▲                     │
                         │                     ▼
                   Metrics & runs       Strategy Engine (RL/Policy)
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

## 4. Integration with Aurora & Forecasting

Kepler is only as good as its inputs. Aurora becomes the default world model:

- **Forecast inputs per slot:** `load`, `pv`.
- **Uncertainty:**
  - Aurora provides uncertainty measures (p10/p50/p90).
  - Strategy Engine uses this to adjust Kepler's safety margins (e.g. `min_soc`).

---

## 5. Strategy Engine: The "Brain"

To get a self-learning system without relying on RL for raw control, we use the Strategy Engine to tune **Kepler policy parameters (`θ`)**:

- `θ_soc_reserve_peak`: minimum SoC during defined peak windows.
- `θ_export_threshold`: minimum price spread vs future to export aggressively.
- `θ_wear_cost`: effective wear cost per kWh cycled.
- `θ_ramping_cost`: penalty for rapid power changes.

**Online Adaptation:**
- **Strategy Engine**: Reads current context (Aurora forecasts, tariffs, weather). Queries a policy model to choose `θ_today`.
- **Kepler**: Uses `θ_today` to build and solve the optimisation.

---

## 6. Roadmap

1.  **Short term** (Completed):
    -   [x] Rename `Oracle` to `Kepler`.
    -   [x] Fix "sawtooth" behavior in `milp_solver.py` (add ramping costs).
    -   [x] Integrate Kepler into `planner.py` as a selectable engine.
2.  **Medium term**:
    -   [x] Promote Kepler to **default planner**.
    -   [ ] Wire Strategy Engine to tune Kepler parameters.
3.  **Long term**:
    -   Full "Agent" mode where Strategy Engine autonomously manages risk.
