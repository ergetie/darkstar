# Darkstar Energy Manager

A Python-based **Model Predictive Control (MPC)** system for optimal residential energy orchestration — battery, export, and **water heating** — now organized as a **monorepo** with a Flask API backend and a React/Vite frontend.

---

## Overview

Darkstar uses a **multi-pass MPC** to minimize cost while respecting device limits and user constraints. Core principles:

* **Exploit cheap windows** for strategic battery charging.
* **Cascading responsibility**: expensive gaps are “owned” by surrounding cheap windows.
* **Hold in cheap windows**: preserve battery for expensive periods rather than discharging into low-value slots.
* **Water heating** is planned as a guaranteed daily energy requirement with bounded deferral.
* **Safety & confidence**: configurable margins and “S-index” factors de-risk forecasts.

The system currently serves a legacy Flask UI while a new React/Vite UI is developed in `frontend/`.

---

## Quick Start

### Prerequisites

* Python **3.12** (see `.python-version`)
* Node.js (only if you want to run the React sandbox)

### Backend (Flask APIs + legacy UI)

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

export FLASK_APP=backend.webapp   # Monorepo path
flask run --host 0.0.0.0 --port 8000
```

> Some environments (e.g., locked sandboxes) block port binding; the layout and code are still correct even if you can’t run locally there.

### Frontend (React/Vite sandbox)

```bash
cd frontend
npm install
npm run dev
```

> The sandbox showcases the new look (dark mode, yellow accent, cards, chart + timeline). API proxying and the full Planning page will land in a later revision.

---

## Project Structure (Monorepo)

```
.
├── backend/                  # Flask app (APIs + legacy UI for now)
│   ├── webapp.py
│   ├── templates/
│   ├── static/
│   └── themes/
├── frontend/                 # React (Vite, TS, Tailwind) sandbox UI
│   ├── index.html
│   ├── src/
│   ├── tailwind.config.cjs
│   └── vite.config.ts
├── docs/
│   └── implementation_plan.md
├── planner.py                # Core MPC (kept at repo root for now)
├── inputs.py                 # Data I/O (Nordpool, forecasts, HA)
├── schedule.json             # Latest plan output
├── config.yaml               # System configuration
├── requirements.txt
├── AGENTS.md
└── README.md
```

> Keeping `planner.py` / `inputs.py` at the repo root avoids import churn during the transition.

---

## Configuration

All system parameters live in **`config.yaml`**.

**Battery**

* `capacity_kwh`, `max_charge_kw`, `max_discharge_kw`, `roundtrip_efficiency`
* SoC bounds and initial SoC fallbacks

**Decision thresholds**

* Margins for battery use/export/water heating
* Strategic charge triggers (percentiles, price floors, target SoC)
* Guards against discharging in cheap windows

**Water heating**

* `min_kwh_per_day` and `power_kw` (or `max_kw`)
* Deferral windows: `plan_days_ahead`, `defer_up_to_hours`
* Grid-only vs. battery-permitted behavior (usually **grid-only** to preserve battery)

**Export**

* Enable/disable export, fees, VAT, profit margin
* Export percentile threshold, “peak-only” toggle
* Future price guard to avoid premature export

**Manual planning**

* SoC target ceilings for manual **charge/export/hold** blocks
* How manual blocks merge with optimal plan (`/api/simulate` + `/api/schedule/save`)

**S-index (safety factor)**

* Base factor and optional dynamic weights (PV deficit, temperature, day offsets)
* Used to derate forecasts, enforce safety margins

**Data & pricing**

* Nordpool area/currency/resolution
* Fixed fees, taxes, VAT handling

### Water Heating Scheduler

* Treats `min_kwh_per_day` as a **must-deliver** quota per day.
* Packs water heating into the **cheapest feasible** slots first, subject to deferral limits.
* Any shortfall triggers additional slots later the same day (or next, within bounds).

---

## Architecture & Algorithm

### Core Components

* **`config.yaml`** — master settings
* **`inputs.py`** — Nordpool prices, PV/load forecasts, Home Assistant reads
* **`planner.py`** — multi-pass MPC that emits the 15-min schedule
* **`backend/webapp.py`** — Flask JSON APIs + legacy UI
* **`schedule.json`** — canonical output consumed by the UI

### Multi-Pass MPC (high level)

1. **Safety pass**
   Apply S-index/margins to PV/load forecasts → `adjusted_pv_kwh`, `adjusted_load_kwh`.

2. **Window detection**
   Identify **cheap windows** (relative/absolute thresholds, percentiles) and the complementary **expensive gaps**.

3. **Water heating allocation**
   Allocate the daily quota within cheap windows first; respect `defer_up_to_hours`; prefer **grid** consumption to preserve battery.

4. **Baseline battery simulation**
   Simulate SoC over the horizon under adjusted PV/load + water-heating load → baseline SoC trajectory.

5. **Cascading responsibilities**
   Assign each expensive gap’s required energy to the surrounding cheap windows that “own” it (spillover handles edges).

6. **Strategic charge distribution**
   Place charging inside owning cheap windows subject to `max_charge_kw`, efficiencies, and contiguous-block preference.

7. **Export policy**
   If enabled and profitable (after fees/VAT/guard), schedule export in high-price slots without violating SoC floor or future responsibilities.

8. **SoC target & polishing**
   Emit a stepped **`soc_target_percent`** and finalize slot actions; smooth discontinuities without violating limits.

**Manual overrides**
User blocks (charge/water/export/hold) are **merged** via `/api/simulate` and persisted via `/api/schedule/save`. Manual semantics cap SoC targets or pin actions where appropriate without breaking device limits.

---

## Output Format

**`schedule.json`** contains 15-minute slots with timezone-aware ISO timestamps and:

* `battery_charge_kw`, `battery_discharge_kw` (legacy: `charge_kw`, `discharge_kw`)
* `water_heating_kw`, `export_kwh`
* `import_price_sek_kwh`, `pv_forecast_kwh`, `load_forecast_kwh`
* `projected_soc_percent`, `soc_target_percent`
* Flags like `is_historical`, identifiers like `slot_number`
* Optional `reason` / `priority` annotations and cumulative cost figures

**Status & history** exposed via APIs:

* `status`: current SoC (`value`, `timestamp`), planner meta (planned_at, planner_version)
* `history/soc?date=today`: 15-min SoC points
* `forecast/horizon`: PV/weather horizon lengths

---

## APIs (read-only list, unchanged)

* `/api/schedule`, `/api/schedule/save`, `/api/simulate`
* `/api/run_planner`, `/api/db/current_schedule`, `/api/db/push_current`
* `/api/status`, `/api/history/soc?date=today`, `/api/forecast/horizon`, `/api/initial_state`
* `/api/ha/water_today`, `/api/ha/average`
* `/api/config`, `/api/theme`, `/api/themes`

> The React UI will consume these endpoints directly. During the transition the legacy Flask pages remain available.

---

## Web UI

**Legacy Flask dashboard** (current)

* 48-hour chart: price line; PV/load fills; charge/export/discharge bars; SoC (projected/target/real-time/historic).
* vis-timeline lanes: **Battery**, **Water**, **Export**, **Hold**.
* Manual actions and planner controls (run/simulate/save/reset).
* Theme system: background/foreground/accent + 16-color palette (0–7 series, 8–15 matching button accents). Grid/lanes tinted from palette variables.

**New React/Vite UI** (in `frontend/`)

* Dark mode (deep charcoal, never pure black), yellow accent, JetBrains Mono.
* Floating left rail (Lucide icons), soft cards, chart over timeline.
* Routes planned: **/planning**, **/learning**, **/debug**.
* ASCII **darkstar** identity will remain accessible (about/footer).

---

## Home Assistant Integration

Create **`secrets.yaml`**:

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "<long-lived-access-token>"
  battery_soc_entity_id: "sensor.inverter_battery"
  water_heater_daily_entity_id: "sensor.vvb_energy_daily"
```

Planner/startup behavior:

* Prefer real-time SoC from HA; fall back to config defaults.
* Dashboard shows current SoC, dynamic S-index, and today’s water-heater energy (HA first, SQLite tracker fallback).

---

## Dependencies

* `pandas` — time-series + allocation logic
* `pyyaml` — configuration
* `nordpool` — electricity prices
* `pytz` — timezone handling
* `flask` — API + legacy UI

---

## Deployment & Ops (example flow)

**Server setup**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export FLASK_APP=backend.webapp
flask run --host 0.0.0.0 --port 8000
```

**Automating planner runs**

* A `systemd` timer/service can call the planner at fixed intervals.
* Logs/metrics can be tailed via `journalctl` or forwarded to your stack.
* Release hygiene: standard GitHub flow; keep `config.yaml`/`secrets.yaml` out of VCS.

---

## UI Themes

* Place theme files under **`backend/themes/`** (`.json`, `.yaml`, `.yml`).
* Each theme defines:

  * `background`, `foreground`, optional `accent`, `muted`
  * `palette`: 16 colors (0–7 series colors; 8–15 matching button colors 0↔8, 1↔9, …)
* vis-timeline grid/lanes inherit from palette variables (override via CSS if needed).

---

### Timeline/Grid Colors

The vis-timeline grid and lane separators are styled to match the active theme.

- Time-axis grid (vertical/horizontal lines):
  - Drawn by vis-timeline under `.vis-time-axis .vis-grid` and styled at runtime in `static/js/app.js` (function `applyTimelineGridColor`).
  - The color is taken from the CSS variable `--ds-palette-0`. To change, update your theme’s palette or modify the variable in `:root`.
  - A MutationObserver re-applies the color after vis re-renders so the override persists.

- Lane separators between Gantt lanes and label rows:
  - Controlled by CSS border rules on `.vis-foreground .vis-group` and `.vis-labelset .vis-label`.
  - The color is set to `var(--ds-palette-0)` in `static/css/style.css`. Override those selectors if you want a different color.

Tip: If you want a different grid/separator tint than palette 0, you can either adjust `--ds-palette-0` in your theme or replace the variable in the above selectors with another palette index (e.g., `--ds-palette-6`).

---

## License

**AGPL-3.0**
