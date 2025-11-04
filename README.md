# Darkstar Energy Manager

A Python-based Model Predictive Control (MPC) system for optimal battery and water heating scheduling in residential energy systems.

## Overview

Darkstar Energy Manager implements advanced multi-pass MPC logic to optimize energy costs by:
- Strategic battery charging during low-price periods
- Intelligent water heating scheduling
- Cascading responsibility between time windows
- "Hold in cheap windows" principle to preserve battery for expensive periods

## Quick Start

### Prerequisites
- Python 3.12.0 (see `.python-version`)
- Virtual environment support

### Installation

1. **Clone and setup environment:**
```bash
git clone <repository-url>
cd darkstar
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Create planner data directory (for sqlite telemetry):**
```bash
mkdir -p data
```

4. **Run the planner:**
```bash
python planner.py
```

This will generate `schedule.json` with the optimal energy management plan.

### Test Data Fetching
```bash
python inputs.py
```

### Run Tests
```bash
PYTHONPATH=. python -m pytest -q
```

## Project Structure

```
darkstar/
├── config.yaml                   # Master configuration file
├── inputs.py                     # External data fetching (Nordpool API, forecasts)
├── planner.py                    # Core MPC scheduling logic
├── decision_maker.js             # Ref erence JavaScript implementation
├── schedule.json                 # Generated output schedule
├── requirements.txt              # Python dependencies
├── AGENTS.md                     # Development guidelines for contributors
├── /docs/implementation_plan.md  # Project plan and history
└── README.md                     # This file
```

## Configuration

All system parameters are configurable via `config.yaml`:

- **Battery specifications**: capacity, charge/discharge limits, efficiency
- **Decision thresholds**: margins for battery use, export, water heating
- **Charging strategy**: percentile thresholds, price tolerances, block consolidation tolerance, gap allowance
- **Strategic charging**: floor price triggers, target SoC
- **Water heating**: power requirements, daily duration, max deferral (`plan_days_ahead`, `defer_up_to_hours`)
- **Export controls**: enable export, fees, profit margin, percentile threshold, peak-only toggle, future price guard
- **Manual planning**: SoC targets for manual charge/export actions (caps applied to SoC target signal)
- **S-index**: static or dynamic safety factors (base factor, PV deficit weight, temperature weight, day offsets)
- **Nordpool API**: price area, currency, resolution
- **Pricing**: VAT, fees, taxes

## Architecture & Algorithm

The system is designed for clarity, testability, and separation of concerns. For a detailed history of changes and the implementation rationale, please see the [implementation plan](docs/implementation_plan.md).

### Core Components
- **`config.yaml`**: Master configuration file for all user-configurable parameters.
- **`inputs.py`**: Handles all external data fetching and preparation (Nordpool API, forecasts, Home Assistant).
- **`planner.py`**: Core MPC logic for generating the schedule.
- **`webapp.py`**: Flask-based web UI and diagnostics API layer.
- **`schedule.json`**: The final output: a time-slotted plan of actions.

### Multi-Pass MPC Logic

The planner executes a series of logical passes to build the optimal schedule. All passes operate on a pandas DataFrame, progressively adding data and refining the plan.

1.  **Pass 0: Apply Safety Margins**: Applies `pv_confidence_percent` and `load_safety_margin_percent` from the config to the raw forecasts to create `adjusted_pv_kwh` and `adjusted_load_kwh`. All subsequent passes use these adjusted values.
2.  **Pass 1: Identify Windows**: Implements a two-step logic to identify cheap slots. It first finds slots below a percentile threshold, then uses the maximum price within that set plus a tolerance to define the final `is_cheap` column. It also identifies strategic periods based on PV vs. load forecasts.
3.  **Pass 2: Schedule Water Heating**: Schedules the required daily water heating for today and tomorrow within the 48-hour planning horizon. It finds the cheapest contiguous block(s) for each day, respecting a configurable deferral window. The energy source is chosen economically: PV surplus is used first, followed by the grid. Critically, in cheap windows, water is heated from the grid, not the battery, to preserve stored energy.
4.  **Pass 3: Simulate Baseline Depletion**: Simulates the battery's state of charge over the planning horizon assuming **no grid charging**. This creates a realistic "worst-case" baseline, accounting for the load from the scheduled water heating.
5.  **Pass 4: Allocate Cascading Responsibilities**: The core of the MPC. It calculates the charging `total_responsibility_kwh` for each cheap window. This accounts for future energy gaps, the window's realistic charging capacity (considering load and water heating), strategic carry-forward logic, and applies a dynamic `S-index` safety factor based on PV deficit and temperature forecasts.
6.  **Pass 5: Distribute Charging in Windows**: Takes the responsibilities from Pass 4 and assigns `charge_kw` to the cheapest slots within each window. This pass features **charge block consolidation**, which favors creating longer, contiguous charging blocks by merging adjacent charge slots within a price tolerance, improving battery health.
7.  **Pass 6: Finalize Schedule**: Performs the final, detailed simulation. It crucially enforces the **"Hold in Cheap Windows"** principle, where the battery is not discharged for load during cheap periods. It assigns the final action `classification` for each slot (e.g., 'Charge', 'Discharge', 'Hold', 'Export') and calculates the projected state of charge, cost, and a target SoC for each slot.

### Key Concepts

- **Strategic Periods**: When the PV forecast is less than the load forecast, the system aims to charge to a higher state of charge (`strategic_charging.target_soc_percent`).
- **Cascading Responsibility**: A cheap window will take on the responsibility of charging for a future expensive window's needs if that future window is predicted to have an energy deficit.
- **Hold in Cheap Windows**: To maximize savings, the battery avoids discharging during cheap periods, preserving its stored energy for times when grid prices are high.
- **Peak-Only Export**: Battery export is gated and only occurs during the most expensive price periods (e.g., top 15th percentile), and only if it's profitable and all future needs are covered. PV surplus is not explicitly planned for export; it contributes to the battery's state of charge.
- **Integrated Water Heating**: Water heating is scheduled as part of the overall optimization, ensuring it runs at the cheapest times while its load impact is accounted for in the battery schedule.
## Output Format

The system generates `schedule.json` containing:
- 15-minute time slots with timezone-aware timestamps
- Energy classifications (Charge, Discharge, Hold, pv_charge)
- Power allocations (battery, grid, export, water heating)
- Projected battery state and cost evolution
- `soc_target_percent` stepped signal indicating desired SoC floor/target per slot
- Price and forecast data

## Web UI

The Flask dashboard provides:
- Real-time stats including current SoC, S-index factor, forecast horizons, and water usage.
- A 48-hour chart with SoC, SoC target overlay, PV/load forecasts, charge/discharge/export bars, and theme-aware colours.
- Manual action controls (`add charge`, `add water heating`, `add hold`, `add export`) that feed the simulate endpoint respecting manual semantics.
- Planner controls (`run planner`, `apply manual changes`, `reset to optimal`) arranged for quick workflows.
- Appearance settings that read all themes from `themes/` and allow selecting a palette accent.

## Deployment & Ops

This is a concise end-to-end workflow used in production with a Proxmox LXC.

### 1) GitHub flow (local dev → GitHub → server)

- Local (developer machine):
  - One-time: `git remote add origin git@github.com:<you>/darkstar.git`
  - Commit/push:
    ```bash
    git add -A
    git commit -m "feat: <your change>"
    git push -u origin main
    ```

- Server (LXC): use SSH key auth for Git:
  ```bash
  cd /opt
  git clone git@github.com:<you>/darkstar.git
  cd darkstar
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

- Update on server after new commits:
  ```bash
  cd /opt/darkstar
  git pull --rebase
  source venv/bin/activate
  pip install -r requirements.txt
  ```

### 2) Tmux cheat‑sheet (keep apps running)

```bash
tmux new -s darkstar
# inside tmux
cd /opt/darkstar
source venv/bin/activate
FLASK_APP=webapp flask run --host 0.0.0.0 --port 8000
# detach: Ctrl-b then d
# reattach later: tmux attach -t darkstar
```

You can run the planner in another pane/window:

```bash
tmux new-window -t darkstar:2
cd /opt/darkstar && source venv/bin/activate
python -m bin.run_planner
```

### 3) Scheduler automation (systemd timer)

We recommend a systemd timer over cron. Example units (adjust paths):

`/etc/systemd/system/darkstar-planner.service`
```
[Unit]
Description=Darkstar planner run
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/darkstar
ExecStart=/opt/darkstar/venv/bin/python -m bin.run_planner
User=root
Group=root
``` 

`/etc/systemd/system/darkstar-planner.timer`
```
[Unit]
Description=Run Darkstar planner hourly (08–22 Europe/Stockholm)

[Timer]
OnCalendar=*-*-* 08..22:00:00
Persistent=true
Unit=darkstar-planner.service

[Install]
WantedBy=timers.target
```

Enable and verify:

```bash
systemctl daemon-reload
systemctl enable --now darkstar-planner.timer
systemctl list-timers | grep darkstar
systemctl status darkstar-planner.timer
journalctl -u darkstar-planner.service -n 100 -f
```

### 4) Secrets and DB

Create `/opt/darkstar/secrets.yaml` (not committed):

```yaml
mariadb:
  host: 192.168.0.110
  port: 3306
  database: helios
  user: darkstar
  password: "<password>"

home_assistant:
  url: "http://homeassistant.local:8123"
  token: "<long-lived-token>"
  battery_soc_entity_id: "sensor.inverter_battery"
  water_heater_daily_entity_id: "sensor.vvb_energy_daily"
  consumption_entity_id: "sensor.inverter_total_load_consumption"
```

Enable writing plans to MariaDB in `config.yaml`:

```yaml
automation:
  enable_scheduler: true
  write_to_mariadb: true
```

### 5) Verifying the last plan

- In the UI Stats (Dashboard), you’ll see both:
  - Local Plan: time/version from `schedule.json`
  - Server Plan: time/version from MariaDB `plan_history`

- From the API:
  ```bash
  curl http://127.0.0.1:5000/api/status | jq
  ```

- Load and view the executing plan (from MariaDB) directly in the UI:
  - Use the “load server plan” button (Dashboard).
  - Or API: `GET /api/db/current_schedule`.

### 6) Common ops tasks

- Update & restart web UI (tmux): pull changes, `Ctrl-b d` to detach, reattach with `tmux attach -t darkstar`.
- Check planner runs: `journalctl -u darkstar-planner.service -f`.
- Confirm DB writes: query `current_schedule` and `plan_history` tables.

### 7) One-command release (semi-automated)

Create a tagged release and push with a single command:

```bash
# Patch bump (default): vX.Y.(Z+1)
python -m bin.release -m "fix: <short message>"

# Minor/major bump
python -m bin.release --bump minor -m "feat: <short message>"
python -m bin.release --bump major -m "chore: major release"

# Or set explicit version
python -m bin.release --version v0.13.2 -m "release notes"
```

What it does:
- Ensures you’re on `main` and rebased on `origin/main`.
- Commits staged/untracked changes with your message (if any changes present).
- Creates an annotated tag (vX.Y.Z) and pushes `main` and tags.

Server update (applies the new release):

```bash
cd /opt/darkstar
git fetch --all && git reset --hard origin/main
source venv/bin/activate && pip install -r requirements.txt
FLASK_APP=webapp flask run --host 0.0.0.0 --port 8000
```


## Development

See `AGENTS.md` for comprehensive development guidelines including:
- Build and test commands
- Code style and formatting standards
- Error handling patterns
- Testing and validation requirements

## Dependencies

- `pandas` - Data manipulation and time-series analysis
- `pyyaml` - Configuration file parsing
- `nordpool` - Electricity price data fetching
- `pytz` - Timezone handling
- `flask` - Web UI and diagnostics API layer

## Home Assistant Integration

Configure `secrets.yaml` with:

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "<long-lived-access-token>"
  battery_soc_entity_id: "sensor.inverter_battery"
  water_heater_daily_entity_id: "sensor.vvb_energy_daily"
```

- Planner initial state prefers the `battery_soc_entity_id` value, falling back to config defaults when unavailable.
- Dashboard stats show current SoC, dynamic S-index factor, and today's water heater consumption (HA first, sqlite tracker fallback).

## UI Themes

- Place theme files in the `themes/` directory. Supported formats: JSON (`.json`) and YAML (`.yaml`/`.yml`).
- Each theme defines:
  - `foreground`, `background` (hex colors)
  - optional `accent`, `muted`
  - `palette`: 16 hex colors; indices 0–7 for chart actions, 8–15 for corresponding buttons (0↔8, 1↔9, …).
- The web-app scans the folder on startup. Select themes under Settings → Appearance.

## License

[Add your license information here]
