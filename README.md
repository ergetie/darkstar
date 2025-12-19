# Darkstar Energy Manager

**AI-powered home battery optimization for solar homes.**

Darkstar is a local, privacy-first energy management system that optimizes your home battery, solar production, and electricity costs using machine learning and mathematical optimization.

![Dashboard Preview](docs/images/dashboard-preview.png)

## ✨ Features

- **MILP Optimization** — Kepler solver minimizes electricity costs over a 48-hour rolling horizon
- **ML Forecasting** — Aurora predicts your home's load and PV production patterns
- **Real-time Execution** — Native executor with Home Assistant integration
- **Beautiful Dashboard** — React-based UI with live schedule visualization
- **Automatic Learning** — Self-tuning parameters adapt to your home over time

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/youruser/darkstar.git
cd darkstar

# Copy configuration templates
cp config.default.yaml config.yaml
cp secrets.example.yaml secrets.yaml

# Edit secrets.yaml with your Home Assistant credentials
# Then start with Docker Compose
docker-compose up -d
```

Access the UI at **http://localhost:5000**

### Option 2: Home Assistant Add-on

1. Add the Darkstar repository to your HA Add-on store
2. Install "Darkstar Energy Manager"
3. Configure your HA token in the add-on settings
4. Start the add-on

### Option 3: Manual Installation

See [Developer Guide](docs/DEVELOPER.md) for full manual installation instructions.

## ⚙️ Configuration

### `config.yaml`

Main configuration for your system:

```yaml
# Battery specifications
battery:
  capacity_kwh: 10.0
  min_soc_percent: 15
  max_soc_percent: 95
  max_charge_power_kw: 5.0

# Your Home Assistant sensor mappings
input_sensors:
  battery_soc: sensor.inverter_battery
  total_pv_production: sensor.inverter_pv_total
  total_load_consumption: sensor.inverter_load_total

# Nordpool price area
nordpool:
  price_area: "SE4"
  currency: "SEK"
```

### `secrets.yaml`

Credentials (never committed to git):

```yaml
home_assistant:
  url: "http://your-homeassistant:8123"
  token: "your-long-lived-access-token"

notifications:
  discord_webhook_url: ""  # Optional fallback alerts
```

## 📊 How It Works

Darkstar uses a three-layer intelligence system:

1. **Aurora Vision** — ML models predict your home's energy patterns
2. **Aurora Strategy** — Context-aware decision making (vacation mode, weather, etc.)
3. **Kepler Solver** — MILP optimization generates optimal schedules

The system runs on a 48-hour rolling horizon, re-optimizing every hour to adapt to changing conditions.

For technical details, see [Architecture Documentation](docs/architecture.md).

## 🏠 Home Assistant Integration

Darkstar reads sensors and controls your inverter through Home Assistant:

**Required Sensors:**
- Battery SoC (%)
- Total PV production (kWh)
- Total load consumption (kWh)

**Controlled Entities:**
- Inverter work mode (export/zero-export)
- Battery charging current limits
- Grid charging switch
- Water heater temperature (optional)

## 📱 Dashboard

The web UI provides:

- **Live Schedule** — 48-hour visualization with charge/discharge/export slots
- **Forecasting** — Compare ML predictions vs. actuals
- **Manual Planning** — Override or extend the automated schedule
- **Settings** — Tune parameters without editing YAML files
- **Executor Status** — Real-time execution monitoring

## 🛠️ Development

```bash
# Setup development environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pnpm install --prefix frontend

# Run development server (frontend + backend + scheduler)
pnpm run dev

# Run tests
pytest tests/ -v
```

For full development guidelines, see [Developer Guide](docs/DEVELOPER.md).

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Developer Guide](docs/DEVELOPER.md) | Full installation, configuration, and deployment |
| [Architecture](docs/architecture.md) | Technical deep dive into the system |
| [Development Plan](docs/PLAN.md) | Roadmap and revision history |
| [Legacy MPC](docs/LEGACY_MPC.md) | Documentation for the deprecated heuristic planner |

## 📄 License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

---

Made with ⚡ for the solar-powered home
