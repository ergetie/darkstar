# Darkstar Energy Manager

**An Intelligent Energy Agent for Residential Systems**

Darkstar is a local, privacy-first **AI Agent** that manages your home's energy. Unlike simple schedulers that follow static rules, Darkstar combines deterministic Model Predictive Control (MPC) with machine learning (Aurora) and context-aware strategy to optimize solar usage, battery arbitrage, and appliance scheduling.

## Overview

Darkstar operates on a rolling 48-hour horizon to minimize energy costs and maximize comfort by:
*   **Forecasting**: Predicting load and solar production using the **Aurora ML** engine.
*   **Strategizing**: Adjusting behavior based on context (e.g., "Vacation Mode", "Storm Incoming") via the **Strategy Engine**.
*   **Optimizing**: Scheduling battery charging, discharging, and water heating using a multi-pass **MPC Planner**.

## Quick Start

### Prerequisites
*   **Python 3.12+** (see `.python-version`)
*   **Node.js 18+**
*   **MariaDB** (External persistence)
*   **Home Assistant** (Source of truth for sensors)

For complete requirements, see `requirements.txt`.

### Installation & Setup

1.  **Clone and Setup Environment:**
    ```bash
    git clone <repository-url>
    cd darkstar
    python -m venv venv
    source venv/bin/activate
    ```

2.  **Install Dependencies:**
    ```bash
    # Backend & ML pipeline
    pip install -r requirements.txt

    # Frontend
    npm install
    npm install --prefix frontend
    ```

3.  **Configuration:**
    *   Copy `config.default.yaml` to `config.yaml`.
    *   Create `secrets.yaml` for API keys.
    *   *See the Configuration section below for details.*

4.  **Run Development Environment:**
    Starts the Flask backend (port 5000) and React frontend (port 5173).
    ```bash
    npm run dev
    ```
    Access the UI at **http://localhost:5173**.

---

## Architecture & Algorithm

Darkstar uses a three-layer brain to make decisions.

### 1. Aurora (The Predictor)
Located in `ml/`, Aurora is a LightGBM-based machine learning engine.
*   **Training**: Learns your home's specific patterns from historical data (`planner_learning.db`).
*   **Inference (Dual-Model Forecasting)**: Uses a two-stage pipeline where Model 1 generates base PV/Load forecasts and Model 2 (Aurora Correction) predicts forecast errors via Rolling Averages or LightGBM (depending on data depth), applying clamped corrections before the planner consumes the numbers.
*   **Control**: You can toggle between "Baseline" (7-day average) and "Aurora" (ML) in the UI to verify performance.

### 2. Strategy Engine (The Context Layer)
Located in `backend/strategy/`, this layer injects "common sense" overrides before the mathematical planner runs.
*   **Vacation Mode**: Detects if the home is empty and suppresses water heating.
*   **Weather Variance & Forecast Uncertainty**: Increases safety margins (S-Index) when 48h weather forecasts (cloud cover/temperature) are volatile, effectively reacting to forecast uncertainty.
*   **The Analyst**: Scans prices to find optimal windows for heavy appliances (Dishwasher/Dryer) and advises the user.

### 3. The Planner (The Optimizer)
Located in `planner.py`, the core MPC logic executes in **7 logical passes** to build the schedule:

1.  **Pass 0: Apply Safety Margins**: Ingests forecasts (from Aurora or Baseline) and applies confidence margins.
2.  **Pass 1: Identify Windows**: Identifies "Cheap" and "Expensive" price windows relative to the daily average.
3.  **Pass 2: Schedule Water Heating**: Allocates the cheapest slots for water heating to meet daily energy quotas.
4.  **Pass 3: Simulate Baseline**: Simulates battery depletion based on load to find "Must Charge" gaps.
5.  **Pass 4: Allocate Cascading Responsibilities**: The core logic. Cheap windows accept responsibility for future deficits.
    *   *Strategy Injection*: The Strategy Engine inserts dynamic overrides here (e.g., boosting targets).
6.  **Pass 5: Distribute Charging**: Assigns power to specific slots, consolidating blocks to minimize battery cycling.
7.  **Pass 6: Finalize & Hold**: Enforces the **"Hold in Cheap Windows"** principle—preventing the battery from discharging during cheap times to save energy for peak prices.

## Key Logic Details

### Water Heating Scheduler
The planner treats water heating as a flexible load that must meet a daily quota.
*   **Sources**: It checks the Home Assistant sensor (`water_heater_daily_entity_id`). If `min_kwh_per_day` is already met, no slots are scheduled.
*   **Optimization**: If more energy is needed, it picks the absolute cheapest contiguous blocks in the next 24h.
*   **Grid vs. Battery**: In cheap windows, water is heated from the **grid** (not battery) to preserve stored energy for expensive periods.

### Strategic Battery Control
*   **Cascading Responsibility**: A cheap window at 02:00 will charge enough to cover a deficit at 18:00.
*   **Hold Logic**: If prices are low (e.g., 13:00), the battery will **hold** its charge (idle) rather than covering load, because that energy is worth more at 19:00.
*   **S-Index (Safety Factor)**: A dynamic multiplier applied to charging targets based on solar uncertainty.
*   **Cross-Day Responsibility (Rev 60)**: Cheap windows are expanded based on future (today+tomorrow) net deficits and price levels so the planner charges in the cheapest remaining hours and preserves SoC for tomorrow’s high-price periods, even when the battery is already near its target at runtime.

---

## Configuration

System parameters are defined in `config.yaml`. Credentials live in `secrets.yaml`.

### `config.yaml` (System Definition)
*   **Input Sensors**: Map your canonical sensor names to Home Assistant Entity IDs.
    ```yaml
    input_sensors:
      total_load_consumption: "sensor.inverter_load_total"
      total_pv_production: "sensor.inverter_pv_total"
      battery_soc: "sensor.battery_soc"
      vacation_mode: "input_boolean.vacation"
    ```
*   **System**: Battery capacity (kWh), Max Charge/Discharge (kW), Inverter Efficiency.
*   **Automation**: Configure the internal scheduler interval (e.g., `every_minutes: 60`).
*   **Aurora**: Toggle ML forecasting (`active_forecast_version`).
*   **Advanced Parameters**:
    *   **Charging Strategy**: `price_smoothing_sek_kwh` (hysteresis), `block_consolidation_tolerance` (merging adjacent slots), `gap_allowance`.
    *   **Export Controls**: `percentile_threshold` (peak-only export), `profit_margin`, `future_price_guard`.
    *   **S-Index**: `base_factor`, `pv_deficit_weight`, `temp_weight`. Weather volatility can dynamically scale these weights during chaotic cloud/temperature conditions.

### `secrets.yaml` (Credentials)
*   **Home Assistant**: `url` and `token`.
*   **Database**: MariaDB host/user/pass.
*   **LLM**: API keys for "The Advisor" (e.g., OpenRouter).

---

## Output Format

The system generates `schedule.json` containing:
*   15-minute time slots with timezone-aware timestamps.
*   Numeric power allocations (`charge_kw`, `discharge_kw`, `export_kw`, `water_heater_kw`).
*   Derived `reason` and `priority` signals for UI visualization.
*   Projected battery state and cost evolution.

---

## Repository Structure
Darkstar is a monorepo containing the Python backend, React frontend, and ML pipelines. For full file structure, run `find . -maxdepth 4 -not -path '*/.*' -not -path './frontend/node_modules*' -not -path './venv*' -not -path './__pycache__*'` in the root directory.

```
/
├── backend/            # Flask API, Scheduler, and Strategy Logic
│   ├── strategy/       # Context rules & Analyst logic
│   ├── scheduler.py    # Internal automation runner
│   └── webapp.py       # Main API entrypoint
├── frontend/           # React + Vite Application
│   ├── src/pages/      # Dashboard, Planning, Lab, Forecasting, Settings
│   └── ...
├── ml/                 # AURORA Machine Learning Pipeline
│   ├── models/         # Trained LightGBM models
│   ├── train.py        # Offline training script
│   └── forward.py      # Inference engine
├── inputs.py           # Data ingestion (HA, Nordpool, Aurora)
├── planner.py          # Core MPC Algorithm
└── config.yaml         # User configuration
```

---

## Deployment & Ops

### 1. In-App Scheduler (Recommended)
Darkstar v2 includes an internal scheduler to avoid race conditions.
*   Enable in `config.yaml`: `automation.enable_scheduler: true`.
*   Run the scheduler process: `python -m backend.scheduler`.
*   *Note: Ensure you disable any old systemd/cron timers to prevent duplicate runs.*

### 2. Production Server (Git Flow)
We recommend running Darkstar on a Proxmox LXC or dedicated Pi.
*   **Updates**:
    ```bash
    cd /opt/darkstar
    git pull --rebase
    source venv/bin/activate
    pip install -r requirements.txt
    ```

### 3. Tmux Cheat-Sheet
Keep the backend and scheduler running in the background:
```bash
tmux new -s darkstar
# inside tmux
cd /opt/darkstar && source venv/bin/activate
npm run dev  # OR run backend/scheduler separately
# detach: Ctrl-b then d
# reattach later: tmux attach -t darkstar
```

*   In development, `npm run dev` starts the frontend, backend, and the internal scheduler in one command.

### 4. Verifying Plans
*   **Dashboard**: Shows the "Local Plan" (what the planner just thought) vs "Server Plan" (what is actually in the DB).
*   **Forecasting Tab**: Compare Aurora predictions vs. Actuals to trust the ML.
*   **The Lab**: Run "What-If" simulations on historical data to test config changes safely.

---

## Development Guidelines

1.  **Linting**: Use `black` and `flake8`. (This will ensure your code is automatically formatted and linted before you commit.)
    ```bash
    pre-commit run --all-files
    ```
2.  **Testing**:
    ```bash
    PYTHONPATH=. python -m pytest -q (for regression testing, after significant changes.)
    ```
3.  **UI Themes**: Add custom JSON themes to `backend/themes/`.
4.  **Logs**: Check the **Debug** tab in the UI for real-time logs from the Planner, Scheduler, and Strategy Engine.
5.  **Releases**:
    Create a tagged release and push with a single command:
    ```bash
    # Patch bump (default): vX.Y.(Z+1)
    python -m bin.release -m "fix: <short message>"
    ```

## License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
