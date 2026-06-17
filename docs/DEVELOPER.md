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
    uv pip install -r requirements-dev.txt

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

### Rebase after dev push:
```bash
git pull --rebase
```

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

**Pre-flight Validator** (`planner/preflight.py`): Before Kepler runs, a deterministic validator checks battery config, initial SoC range, EV charger parameters, price/forecast data availability, and numeric sanity. Blocking failures raise `PlannerError` with a typed error code; non-blocking conditions (stale SoC, past EV deadlines) log warnings and continue.

**Error Code Taxonomy** (`planner/errors.py`): Every planner failure produces a `PlannerErrorCode` enum value (e.g., `CONFIG_INVALID`, `SOLVER_INFEASIBLE`, `PRICES_UNAVAILABLE`) with a human-readable `user_message()` and actionable `fix_hints()`. The `PlannerError` exception carries code, message, fix hint, and a structured details dict.

**Retry Policy** (`backend/services/planner_service.py`): After a failure, the `PlannerService` applies a retry policy keyed on error code category: config-blocking errors suspend retries until settings are saved; transient errors use exponential backoff (60s → 120s → 240s → 300s cap); invariant errors retry at normal 60s cadence; warning-only codes do not block scheduling.

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

### Manual ML Training
You can manually trigger training using the script:
```bash
python scripts/train_corrector.py [--force]
```
- **Standard Run**: Respects graduation level logic (needs 14 days of data).
- **Force Run** (`--force`): Bypasses checks and trains models immediately (useful for testing).


For a deep dive into the solver logic, see [architecture.md](architecture.md).

### Configuration & Migrations
Darkstar prioritizes a "zero-touch" update experience. If you introduce breaking changes to `config.yaml` or the SQLite schema:

1.  **Config Migrations**: Register a new `MigrationStep` in `backend/config_migration.py`.
    - These steps run automatically during the `backend/main.py` startup lifespan.
    - **Structure Enforcement (Template Fill)**: Darkstar strictly enforces the structure and comments of `config.default.yaml`. It uses the default file as a template and injects user values into it.
    - **Custom Keys**: Keys present in `config.yaml` but missing from the default are preserved and appended to the end of their respective sections (or the root).
    - **Safety**: A `.bak` backup is automatically created before any configuration write.
    - Use `ruamel.yaml` (already integrated in the migration pipeline) to handle round-trip processing.
2.  **Database Migrations**: Darkstar uses **Alembic** for versioned migrations.
    - **Applying Migrations**: Run automatically on startup via `alembic upgrade head`.
    - **Creating Migrations**: If you change a model in `backend/learning/models.py`, generate a new migration:
      ```bash
      alembic revision --autogenerate -m "description of change"
      ```
    - **Dynamic Path**: Alembic is configured to respect the `DB_PATH` environment variable.
3.  **Fallback Logic**: When feasible, implement temporary "Plan B" fallbacks in Python code to handle both old and new key names until the next major release.

4.  **Async Migration (ARC11)**: Background services (Recorder, Analyst, etc.) were migrated to 100% AsyncIO. All database operations MUST use `AsyncSession`. Do not use the legacy `Session()` class as it has been removed.

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
    *   **ML Training**: Configure the automatic training schedule.
        ```yaml
        automation:
          ml_training:
            enabled: true
            run_days: [1, 4]  # 0=Monday, 6=Sunday. Default: Tue, Fri
            run_time: "03:00" # Local time (24h format)
        ```
        *   **Automatic Training**: Retrains the model periodically (default: twice a week).
        *   **Training Lock**: Uses a lock file (`ml/models/.training.lock`) to prevent concurrent runs.
        *   **Error Correction**: Automatically trains "Correction Models" if the system has enough data ("Graduate" level, >14 days).
*   **Advanced Parameters**:
    *   **Charging Strategy**: `price_smoothing_sek_kwh` (hysteresis), `block_consolidation_tolerance` (merging adjacent slots), `gap_allowance`.
    *   **Export Controls**: `export_percentile_threshold` (peak-only export), `export_profit_margin_sek`, `export_future_price_guard`, `future_price_guard_buffer_sek`, and `protective_soc_strategy` (`gap_based` vs `fixed_protective_soc_percent`).
    *   **S-Index**: `mode` (`probabilistic` or `dynamic`), `s_index_horizon_days` (1-7 days), `risk_appetite` (1-5 scale), `base_factor`, `max_factor`. Uses extended Aurora probabilistic forecasts (p10/p50/p90) for D+1 to D+4, even when Nordpool prices only cover today/tomorrow.

*   **Home Assistant**: `url` and `token`.
*   **LLM**: API keys for "The Advisor" (e.g., OpenRouter).

### Water Heating Comfort Levels (Rev K24)
The "Comfort Level" slider (1-5) controls the trade-off between reliability (getting hot water) and economy (waiting for cheap prices).

**Rev K24 introduces dynamic window sizing** - the system adapts heating block sizes based on your actual heater configuration (power rating and daily requirement).

**Two-Parameter System:**
1. **Window Size (`max_block_hours`)** - Calculated dynamically: `(daily_kwh / heater_power_kw) × comfort_multiplier`
2. **Penalties** - Applied when constraints are violated

**Comfort Level Mapping:**

| Level | Name     | Window Multiplier | Reliability Penalty | Block Start Penalty | Block Penalty | Behavior                                         |
| :---- | :------- | :---------------- | :------------------ | :------------------ | :------------ | :----------------------------------------------- |
| **1** | Economy  | 1.5×              | 2.0 SEK/day         | 1.5 SEK/block       | 0.5 SEK/slot  | Large windows = bulk heating in cheapest periods |
| **2** | Balanced | 1.0×              | 7.0 SEK/day         | 2.25 SEK/block      | 1.0 SEK/slot  | Moderate windows = balanced approach             |
| **3** | Neutral  | 0.8×              | 15.0 SEK/day        | 3.0 SEK/block       | 2.0 SEK/slot  | **Default.** Slight spacing preference           |
| **4** | Priority | 0.5×              | 30.0 SEK/day        | 4.5 SEK/block       | 5.0 SEK/slot  | Small windows = more frequent heating            |
| **5** | Maximum  | 0.25×             | 300.0 SEK/day       | 1.0 SEK/block       | 10.0 SEK/slot | Tiny windows = very frequent heating             |

**Example:** 3kW heater, 8kWh daily requirement (2.67h minimum heating time)
- Level 1: 4.0h windows → 2 blocks per day
- Level 3: 2.1h windows → 3-4 blocks per day
- Level 5: 0.67h windows → 7-8 blocks per day

**Bulk Mode Override:**
Set `enable_top_ups: false` to surgically override block parameters:
- `max_block_hours = 24.0` (allow entire day as one block)
- `water_block_penalty_sek = 0.0` (no penalty for long blocks)
- Preserves reliability and block start penalties from comfort level

This allows users to request bulk heating while maintaining their chosen reliability level (e.g., Level 5 + bulk mode = strict reliability but consolidated heating).

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
├── backend/
│   ├── core/
│   │   ├── secrets.py    # Config/secrets loading (YAML, HA config)
│   │   ├── ha_client.py  # Home Assistant HTTP sensor access
│   │   ├── prices.py     # Nordpool electricity price fetching
│   │   ├── forecasts.py  # PV/load forecast orchestration
│   │   ├── cache.py      # TTL cache (async/sync)
│   │   ├── logging.py    # Logging utilities
│   │   └── websockets.py # WebSocket manager
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
    source .venv/bin/activate
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
    uv run python -m pytest -q (for regression testing, after significant changes.)
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

### How It Works (Dev on Main)
We support a "Dev on Main" workflow to allow rapid iteration without spamming the main branch history.

1. **Push to `main` (Recommended)**:
    *   **Action**: Development work is committed and pushed to `main`.
    *   **CI Trigger**: Builds the `ergetie/darkstar-dev` Docker image targeting `amd64` (for speed).
    *   **Version Bump**: The CI checkout the `dev` branch, updates the version in `darkstar-dev/config.yaml` to `dev-YYYYMMDD.HHMM`, and pushes this **only to the `dev` branch**.
    *   **Result**: Your `main` branch stays clean (no version bump commits), but your Home Assistant (tracking `URL#dev`) sees the update immediately.

2. **Push to `dev` (Legacy/Testing)**:
    *   **Action**: Pushing directly to `dev` works identically to `main`. It builds the dev image and self-updates the version string on the `dev` branch.

3.  **Releases (Production)**:
    *   **Action**: Tag a commit on `main` with `vX.Y.Z`.
    *   **CI Trigger**: Builds `ergetie/darkstar` (Production) for both `amd64` and `aarch64`.
    *   **Release**: Creates a GitHub Release with notes extracted from `docs/RELEASE_NOTES.md`.

### Summary of Git Flow
| Action             | Build Target      | Architectures       | Updates HA?        | Git History    |
| :----------------- | :---------------- | :------------------ | :----------------- | :------------- |
| **Push to `main`** | `darkstar-dev`    | `amd64`             | ✅ (via dev branch) | Clean          |
| **Push to `dev`**  | `darkstar-dev`    | `amd64`             | ✅                  | Contains Bumps |
| **Tag `v*`**       | `darkstar` (Prod) | `amd64` + `aarch64` | ✅                  | Release Tag    |

### Local Development
If you are developing locally on a different architecture (e.g., Apple Silicon), it is recommended to test the standard `darkstar/` build or run via `pnpm run dev` directly as described in the Quick Start.

## Live Profiling (py-spy)

To debug CPU hotspots or GIL serialization latency in production or during runtime, you can run `py-spy` against the containerized Python processes.

### Prerequisites
1. Ensure the `darkstar` container has the `SYS_PTRACE` capability enabled in your `docker-compose.yml`:
   ```yaml
   cap_add:
     - SYS_PTRACE
   ```
2. Restart the container if you modified `docker-compose.yml`:
   ```bash
   docker compose down && docker compose up -d
   ```

### Profiling Steps
1. Exec into the running container as root:
   ```bash
   docker exec -it --user root darkstar bash
   ```
2. Install `py-spy` inside the container:
   ```bash
   pip install py-spy
   ```
3. Locate the Python process ID:
   ```bash
   ps aux | grep python
   ```
4. Record a profile or dump call stacks:
   * **Stack Dump** (shows what all threads are currently doing):
     ```bash
     py-spy dump --pid <PID>
     ```
   * **Live Top** (like top command for Python functions):
     ```bash
     py-spy top --pid <PID>
     ```
   * **Generate Flame Graph** (records 30 seconds of activity to an SVG):
     ```bash
     py-spy record -o /app/profile.svg --pid <PID> --duration 30
     ```
     The output SVG will be generated in `/app/` (which maps to your workspace directory on the host if bind-mounted) for easy viewing.

## License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
