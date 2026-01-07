# Darkstar Setup Guide

Welcome to the Darkstar Public Beta! This guide will walk you through the initial configuration to get your energy management system running optimally.

## 📋 Prerequisites

Before starting, ensure you have:
1.  **Home Assistant** up and running.
2.  **Long-Lived Access Token** from Home Assistant (Profile -> Security -> Long-lived access tokens).
3.  **Solar/Battery/Inverter Data** available in Home Assistant.
4.  (Optional) **OpenRouter API Key** for the AI Advisor features.

---

## 🛠️ Step 1: Configuration (`config.yaml`)

The `config.yaml` file defines your physical hardware and connection points.

### 1.1 System Location
Set your coordinates and timezone. This is critical for accurate solar forecasting.
```yaml
timezone: "Europe/Stockholm"
system:
  location:
    latitude: 59.3293
    longitude: 18.0686
```

### 1.2 Battery Specs
Define your battery capacity and safe operating limits.
```yaml
battery:
  capacity_kwh: 10.0      # Total usable capacity
  min_soc_percent: 15     # Minimum floor (don't discharge below this)
  max_soc_percent: 95     # Default charge ceiling
  max_charge_power_kw: 5.0
```

### 1.3 Home Assistant Sensors
Map your HA entity IDs so Darkstar can read your real-time data.
> [!TIP]
> You can find these IDs in Home Assistant under **Settings -> Devices & Services -> Entities**.

```yaml
input_sensors:
  battery_soc: sensor.your_battery_soc
  pv_power: sensor.your_pv_production_power
  load_power: sensor.your_home_load_power
```

---

## 🔑 Step 2: Secrets (`secrets.yaml`)

For security, sensitive data is stored in `secrets.yaml`. This file is ignored by git.

1.  Copy `secrets.example.yaml` to `secrets.yaml`.
2.  Fill in your Home Assistant URL and Token:
```yaml
home_assistant:
  url: "http://192.168.1.100:8123"
  token: "your-long-token-here"
```

---

## 🚀 Step 3: Deployment

### Home Assistant Add-on
If using the Add-on:
1.  Click the "Add Repository" button in the README or manually add `https://github.com/ergetie/darkstar`.
2.  Install and Start.
3.  The Add-on will automatically use the `config.yaml` and `secrets.yaml` you create in the `/config/darkstar` folder (or via the UI).

### Docker Compose
```bash
docker-compose up -d
```

---

## ✅ Step 4: Verification

1.  Open the Dashboard (**http://localhost:5000** or via the HA sidebar).
2.  Check the **Status** card. It should show "Healthy" and display your current battery SoC.
3.  View the **Schedule** tab. After a few minutes, you should see the first generated 48-hour plan.

---

## 🆘 Need Help?
If the planner isn't generating a schedule:
- Check logs for "Failed to fetch Home Assistant entity" errors.
- Ensure your `timezone` matches your Home Assistant system timezone.
- Verify that your sensors provide numeric values (check the HA States developer tool).
