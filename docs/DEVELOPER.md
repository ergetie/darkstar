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

*   **Home Assistant** (Source of truth for sensors)

For complete requirements, see `requirements.txt`.

### Installation & Setup

1.  **Clone and Setup Environment:**
    ```bash
    git clone <repository-url>
    cd darkstar

    # ⚡ Install uv (The blazing fast Python manager)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Create virtual environment
    uv venv

    ```

2.  **Install Dependencies:**
    ```bash
    # Backend & ML pipeline
    uv pip install -r requirements.txt

    # Frontend
    pnpm install
    pnpm install --prefix frontend
    ```

3.  **Configuration:**
    *   Copy `config.default.yaml` to `config.yaml`.
    *   Create `secrets.yaml` for API keys.
    *   *See the Configuration section below for details.*

4.  **Run Development Environment:**
    Starts the FastAPI backend (port 5000) and React frontend (port 5173).
    ```bash
    pnpm run dev
    ```
    Access the UI at **http://localhost:5173**.

    > [!IMPORTANT]
    > **WebSockets & Concurrency**: The backend must run via `python backend/run.py` (which `pnpm run dev` does automatically) to enable the Uvicorn-based async server. Direct `uvicorn` invocation for development is also supported.

### Update:
```bash
git pull
docker compose up -d --build
docker compose logs -f
```
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

### Database Management
Darkstar uses SQLite (`data/planner_learning.db`) managed via **SQLAlchemy ORM**.
- **Models**: All tables are defined as declarative models in [backend/learning/models.py](backend/learning/models.py).
- **Optimize:** Run `python scripts/optimize_db.py` to backup, trim old history, and vacuum the database.
- **Profile:** Run `python scripts/profile_db.py` to analyze table sizes and performance.
- **Planner Profile:** Run `python scripts/profile_planner.py` to benchmark the planner pipeline.

For a deep dive into the solver logic, see [architecture.md](architecture.md).

### Configuration & Migrations
Darkstar prioritizes a "zero-touch" update experience. If you introduce breaking changes to `config.yaml` or the SQLite schema:

1.  **Config Migrations**: Register a new `MigrationStep` in `backend/config_migration.py`.
    - These steps run automatically during the `backend/main.py` startup lifespan.
    - Use `ruamel.yaml` to ensure user comments/formatting are preserved.
2.  **Database Migrations**: Darkstar uses **Alembic** for versioned migrations.
    - **Applying Migrations**: Run automatically on startup via `alembic upgrade head`.
    - **Creating Migrations**: If you change a model in `backend/learning/models.py`, generate a new migration:
      ```bash
      alembic revision --autogenerate -m "description of change"
      ```
    - **Dynamic Path**: Alembic is configured to respect the `DB_PATH` environment variable.
3.  **Fallback Logic**: When feasible, implement temporary "Plan B" fallbacks in Python code to handle both old and new key names until the next major release.

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

*   **Home Assistant**: `url` and `token`.
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
├── backend/            # FastAPI API, Scheduler, and Strategy Logic
│   ├── strategy/       # Context rules & Analyst logic
│   └── main.py         # FastAPI application entrypoint
├── executor/           # Native Executor (replaces n8n workflow)
│   ├── engine.py       # 5-minute tick loop
│   ├── controller.py   # Action determination
│   ├── override.py     # Real-time override logic
│   └── actions.py       # HA service dispatcher
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
*   **Dashboard**: Shows the "Local Plan" (what the planner just thought).
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

### Commit Protocol (Strict)
This project enforces **Conventional Commits** automatically via `commitlint`.
All commit messages MUST follow the format: `type(scope): description`.

- ✅ `fix(api): handle timeout error`
- ✅ `feat(ui): add dark mode toggle`
- ❌ `fixed api` (Will be rejected)

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`.

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
    3. **Automated Release**:
       - The GitHub Actions workflow will automatically build the Docker image.
       - It will also parse `docs/RELEASE_NOTES.md` and create a **GitHub Release** with the corresponding notes.
       - **Do not manually create releases in the GitHub UI**, as this triggers redundant builds.
    The sidebar fetches version from `/api/version` which uses `git describe --tags`.

## Troubleshooting & Debugging

### Socket.IO Diagnostics
If you encounter WebSocket connection issues (especially through Home Assistant Ingress), you can enable verbose frontend logging by adding `debug=true` to the URL:

`http://localhost:5173/?debug=true`

This will output detailed connection lifecycle events, transport details, and packet data to the browser console.

**Advanced Overrides:**
You can also force specific Socket.IO parameters via the URL for testing:
*   `socket_path=/custom/path`: Override the service worker path.
*   `socket_transports=websocket,polling`: Force specific transports.

## Dev Branch & Add-on Workflow

For rapid debugging and feature testing, we use a separate **Dev Add-on** channel:

- **Branch**: `dev`
- **Add-on**: `[DEV] Darkstar Energy Manager`
- **Image**: `ghcr.io/ergetie/darkstar-dev-amd64`

### How It Works
1. **Push to `dev`**: Any push to the `dev` branch triggers the GitHub Action.
2. **AMD64 Optimization**: To keep iteration fast, the dev build only targets `amd64`.
3. **Dynamic Versioning**: The CI automatically bumps the version in `darkstar-dev/config.yaml` to `dev-YYYYMMDD.HHMM`.
4. **HA Updates**: Because the version string changes every time, Home Assistant will show an **Update** button in the Add-on Store/Dashboard automatically.
5. **Merging**: Once a feature is stable in `dev`, it should be merged into `main` and tagged for a formal release.

### Local Development
If you are developing locally on a different architecture (e.g., Apple Silicon), it is recommended to test the standard `darkstar/` build or run via `pnpm run dev` directly as described in the Quick Start.

## License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
