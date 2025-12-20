# Darkstar Energy Manager

**AI-powered home battery optimization for solar homes.**

Darkstar is a local, privacy-first energy management system that optimizes your home battery, solar production, and electricity costs using machine learning and mathematical optimization.

![Dashboard Preview](docs/images/dashboard-preview.png)

## ✨ Features

- **Smart Optimization** — Minimizes electricity costs over a 48-hour rolling horizon
- **ML Forecasting** — Learns your home's load and PV production patterns
- **Real-time Execution** — Automatic inverter control via Home Assistant
- **Beautiful Dashboard** — React-based UI with live schedule visualization
- **Self-Learning** — Parameters auto-tune to your home over time

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/ergetie/darkstar.git
cd darkstar

# Copy configuration templates
cp config.default.yaml config.yaml
cp secrets.example.yaml secrets.yaml

# Edit secrets.yaml with your Home Assistant credentials
# Then start with Docker Compose
docker-compose up -d
```

To update:
```bash
cd /opt/darkstar
git pull origin main
docker compose build
docker compose down && docker compose up -d
docker compose logs -f
```

Access the UI at **http://localhost:5000**

### Option 2: Home Assistant Add-on

1. Add the Darkstar repository to your HA Add-on store
2. Install "Darkstar Energy Manager"
3. Configure your HA token in the add-on settings
4. Start the add-on

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

openrouter_api_key: "sk-or-v1-..."

notifications:
  discord_webhook_url: ""  # Optional fallback alerts
```

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

## 📊 How It Works

1. **Forecasting** — Aurora ML predicts your home's energy patterns
2. **Strategy** — Context-aware adjustments (vacation mode, weather, etc.)
3. **Optimization** — Kepler solver generates optimal battery schedules
4. **Execution** — Native executor controls your inverter in real-time

The system re-optimizes every hour to adapt to changing prices and conditions.

## 📄 License

Licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

