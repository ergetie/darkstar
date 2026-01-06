# Darkstar Developer Guide

> **Note**: For quick start and installation, see the main [README.md](../README.md).

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
    pnpm install
    pnpm install --prefix frontend
    ```

3.  **Configuration:**
    *   Copy `config.default.yaml` to `config.yaml`.
    *   Create `secrets.yaml` for API keys.
    *   *See the Configuration section below for details.*

4.  **Run Development Environment:**
    Starts the Flask backend (port 5000) and React frontend (port 5173).
    ```bash
    pnpm run dev
    ```
    Access the UI at **http://localhost:5173**.

    > [!IMPORTANT]
    > **WebSockets & Concurrency**: The backend must run via `python backend/run.py` (which `pnpm run dev` does automatically) to enable the `eventlet` WebSocket server. Standard `flask run` is NOT compatible with our production WebSocket features.

---

## Architecture & Algorithm

Darkstar uses a three-layer brain to make decisions.

### 1. Aurora Vision (The Predictor)
Located in `ml/`, Aurora Vision is a LightGBM-based machine learning engine.
*   **Training**: Learns your home's specific patterns from historical data (`planner_learning.db`).
*   **Inference**: Generates base PV/Load forecasts and predicts forecast errors via Rolling Averages or LightGBM (depending on data depth).
*   **Control**: You can toggle between "Baseline" (7-day average) and "Aurora" (ML) in the UI.

### 2. Aurora Strategy (The Context Layer)
Located in `backend/strategy/`, this layer injects "common sense" overrides before the mathematical planner runs.
*   **Vacation Mode**: Detects if the home is empty and suppresses water heating.
*   **Weather Variance**: Increases safety margins (S-Index) when 48h weather forecasts are volatile.
*   **The Analyst**: Scans prices to find optimal windows for heavy appliances.

### 3. Aurora Reflex (The Balancer)
Located in `backend/learning/reflex.py`, this is the long-term feedback loop.
*   **Auto-Tuning**: Analyzes historical drift to tune physical constants (e.g., Battery Capacity) and policy weights (e.g., Safety Margins).
*   **Safe Updates**: Automatically updates `config.yaml` while preserving comments and logging changes.
*   **Analyzers**: Monitors Safety (S-Index), Confidence (PV Bias), ROI (Virtual Cost), and Capacity.

### 3. The Planner (The Optimizer)
Located in `planner.py`, the system now uses **Kepler**, a Mixed-Integer Linear Programming (MILP) solver, to generate optimal schedules.

*   **Objective**: Minimizes total cost (Import - Export + Wear) over a 48h horizon.
*   **Constraints**: Respects battery capacity, inverter limits, and energy balance.
*   **Strategic S-Index**: Applies a decoupled safety strategy:
    *   **Load Inflation**: Buffers against today's forecast errors.
    *   **Dynamic Target SoC**: Buffers against tomorrow's risks (e.g., low PV).
*   **Water Heating**: Scheduled as a "committed load" before the battery optimization runs.

For a deep dive into the solver logic, see [architecture.md](architecture.md).

> **Note:** The legacy heuristic MPC planner (7-pass logic) is preserved for reference in [LEGACY_MPC.md](LEGACY_MPC.md).

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
    *   **Export Controls**: `export_percentile_threshold` (peak-only export), `export_profit_margin_sek`, `export_future_price_guard`, `future_price_guard_buffer_sek`, and `protective_soc_strategy` (`gap_based` vs `fixed_protective_soc_percent`).
    *   **S-Index**: `mode` (`probabilistic` or `dynamic`), `s_index_horizon_days` (1-7 days), `risk_appetite` (1-5 scale), `base_factor`, `max_factor`. Uses extended Aurora probabilistic forecasts (p10/p50/p90) for D+1 to D+4, even when Nordpool prices only cover today/tomorrow.

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
├── executor/           # Native Executor (replaces n8n workflow)
│   ├── engine.py       # 5-minute tick loop
│   ├── controller.py   # Action determination
│   ├── override.py     # Real-time override logic
│   └── actions.py      # HA service dispatcher
├── frontend/           # React + Vite Application
│   ├── src/pages/      # Dashboard, Planning, Lab, Forecasting, Executor, Settings
│   └── ...
├── ml/                 # AURORA Machine Learning Pipeline
│   ├── models/         # Trained LightGBM models
│   ├── train.py        # Offline training script
│   └── forward.py      # Inference engine
├── planner/            # Modular Planner Package
│   ├── pipeline.py     # Main orchestrator
│   ├── solver/         # Kepler MILP solver
│   └── strategy/       # S-Index, Target SoC
├── inputs.py           # Data ingestion (HA, Nordpool, Aurora)
└── config.yaml         # User configuration
```

---

## Deployment & Ops

### 1. In-App Scheduler + Recorder + Executor
Darkstar v2 includes an internal scheduler, recorder, and native executor that all start automatically.

**Scheduler:**
*   Enable planner automation in `config.yaml`:
    ```yaml
    automation:
      enable_scheduler: true
      schedule:
        every_minutes: 60
        jitter_minutes: 0
    ```
*   Runs the planner periodically to regenerate schedules

**Executor:**
*   Enable executor in `config.yaml`:
    ```yaml
    executor:
      enabled: true           # Auto-starts on application launch
      interval_seconds: 300   # Runs every 5 minutes
    ```
*   **Auto-starts when application launches** if `enabled: true`
*   Executes planned actions (battery control, water heating)
*   No manual UI interaction required after restart

**Recorder:**
*   Logs live energy observations every 15 minutes
*   Feeds Aurora ML training data

**Development Mode:**
*   In development, `pnpm run dev` starts:
    *   Frontend dev server (Vite)
    *   Backend API server (FastAPI)
    *   Scheduler (background task)
    *   Executor (background thread)
    *   Recorder (15-minute observation loop)

### 2. Production Server (Git Flow)
We recommend running Darkstar on a Proxmox LXC or dedicated Pi.
*   **Updates**:
    ```bash
    cd /opt/darkstar
    git pull --rebase
    source venv/bin/activate
    pip install -r requirements.txt
    ```

### 3. Systemd + Tmux Cheat-Sheet

**Systemd (server/LXC)**
To auto-start Darkstar on boot via systemd:

1. Create `/etc/systemd/system/darkstar.service`:
    ```ini
    [Unit]
    Description=Darkstar dev stack (backend + recorder + frontend)
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    WorkingDirectory=/opt/darkstar
    ExecStart=/usr/bin/pnpm run dev
    Restart=on-failure
    Environment=NODE_ENV=production
    Environment=PYTHONPATH=.

    [Install]
    WantedBy=multi-user.target
    ```
2. Enable and start:
    ```bash
    systemctl daemon-reload
    systemctl enable darkstar
    systemctl start darkstar
    systemctl status darkstar
    ```

**Tmux (manual/dev)**
Keep the backend and scheduler/recorder running in the background:
```bash
tmux new -s darkstar
# inside tmux
cd /opt/darkstar && source venv/bin/activate
pnpm run dev  # OR run backend/scheduler separately
# detach: Ctrl-b then d
# reattach later: tmux attach -t darkstar
```

### 4. Verifying Plans
*   **Dashboard**: Shows the "Local Plan" (what the planner just thought) vs "Server Plan" (what is actually in the DB).
*   **Forecasting Tab**: Compare Aurora predictions vs. Actuals to trust the ML.
*   **The Lab**: Run "What-If" simulations on historical data to test config changes safely.

---

## Development Guidelines

1.  **Linting**: Use `ruff` for linting/formatting and `pyright` for type checking.
    ```bash
    ruff format .        # Format code (Black-compatible)
    ruff check --fix .   # Lint and auto-fix issues
    pyright .            # Type check (strict mode)
    # Or run all at once:
    ./lint.sh
    ```
2.  **Testing**:
    ```bash
    PYTHONPATH=. python -m pytest -q (for regression testing, after significant changes.)
    ```
3.  **UI Themes**: Add custom JSON themes to `backend/themes/`.
4.  **Logs**: Check the **Debug** tab in the UI for real-time logs from the Planner, Scheduler, and Strategy Engine.
5.  **Releases**:
    When releasing a new version:
    1. **Bump version** in:
       - `darkstar/config.yaml` (add-on manifest)
       - `darkstar/run.sh` (startup banner)
       - `frontend/package.json`
    2. **Tag and push**:
       ```bash
       git tag vX.Y.Z
       git push origin vX.Y.Z
       ```
       (This automatically triggers the CI/CD build.)
    The sidebar fetches version from `/api/version` which uses `git describe --tags`.

## License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
