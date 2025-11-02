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
├── config.yaml              # Master configuration file
├── inputs.py                # External data fetching (Nordpool API, forecasts)
├── planner.py               # Core MPC scheduling logic
├── decision_maker.js        # Reference JavaScript implementation
├── schedule.json            # Generated output schedule
├── requirements.txt         # Python dependencies
├── AGENTS.md                # Development guidelines for contributors
├── project_plan_v3.md       # **Authoritative system architecture**
└── README.md              # This file
```

## Configuration

All system parameters are configurable via `config.yaml`:

- **Battery specifications**: capacity, charge/discharge limits, efficiency
- **Decision thresholds**: margins for battery use, export, water heating
- **Charging strategy**: percentile thresholds, price tolerances, block consolidation tolerance, gap allowance
- **Strategic charging**: floor price triggers, target SoC
- **Water heating**: power requirements, daily duration
- **Export controls**: enable export, fees, profit margin, percentile threshold, peak-only toggle, future price guard
- **S-index**: static or dynamic safety factors (base factor, PV deficit weight, temperature weight, day offsets)
- **Nordpool API**: price area, currency, resolution
- **Pricing**: VAT, fees, taxes

## Architecture & Algorithm

**⚠️ Important**: `project_plan_v3.md` is the main source of truth for system architecture. Later the `gap_analysis.md` has been added and `implementation_plan.md` is the working document.

### Multi-Pass MPC Logic

The planner executes these logical passes:

1. **Pass 0**: Apply safety margins to forecasts
2. **Pass 1**: Identify cheap price windows using two-step percentile logic
3. **Pass 2**: Schedule water heating with dynamic source selection
4. **Pass 3**: Simulate baseline battery depletion
5. **Pass 4**: Allocate cascading responsibilities between windows
6. **Pass 5**: Distribute charging within windows
7. **Pass 6**: Finalize schedule with "Hold in cheap windows" principle

### Key Concepts

- **Strategic Periods**: When PV forecast < Load forecast, charge to absolute SoC target
- **Cascading Responsibility**: Current window charges for future window's needs if insufficient
- **Hold in Cheap Windows**: Preserve battery during low-price periods for expensive periods ahead
- **Integrated Water Heating**: Water heating scheduled within planner to account for load impact

## Output Format

The system generates `schedule.json` containing:
- 15-minute time slots with timezone-aware timestamps
- Energy classifications (Charge, Discharge, Hold, pv_charge)
- Power allocations (battery, grid, export, water heating)
- Projected battery state and cost evolution
- Price and forecast data

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
