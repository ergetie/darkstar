# Darkstar Configuration Guide

> [!IMPORTANT]
> **HAVE YOU INSTALLED YET?**
> This guide is for *configuring* Darkstar after it is running. If you haven't installed the software yet, please follow the [README.md Installation Steps](https://github.com/ergetie/darkstar/README.md#installation) first.

Welcome to the Darkstar Public Beta! This guide will walk you through tuning your system for maximum savings and safety. All changes should be made via the **Settings** tab in the Darkstar Web UI. You can also directly edit the config.yaml file if you prefer, but that requires a restart of the Darkstar service after changes.

---

## 🛠️ Part 1: The Basics (System & Location)

Navigate to **Settings -> System**. These are the "foundations" of your optimization.

### 1.1 System Profile
Enable the hardware you actually have.
- **Solar panels installed**: Enable this to activate PV forecasting.
- **Home battery installed**: Enable for battery arbitrage logic.
- **Smart water heater**: Enable if you want Darkstar to control your boiler.
- **Export**: This setting is currently not active.

### 1.2 Location & Solar Array
Darkstar uses the **Open-Meteo API** to predict your solar production based on weather forecasts.
- **Latitude / Longitude**: Must be accurate for weather-based forecasting.
- **Solar Azimuth / Tilt**: 180° Azimuth is South. Tilt is the angle of your panels.
- **Solar Capacity (kWp)**: The total peak DC power of your panels (e.g., 10.5).

### 1.3 Battery Specifications
- **Battery Capacity (kWh)**: Total usable energy storage. (Critical: Incorrect values break the planner!)
- **Charge/Discharge Power (kW)**: The power limits of your inverter.
- **Min/Max SoC (%)**: Your safe operating range (e.g., 12% to 100%), Darkstar will not plan outside of this range. 

### 1.4 Pricing & Timezone
- **Nordpool Price Area**: Your region (e.g., `SE4`, `NO1`, `FI`).
- **Timezone**: Must be in **IANA format** (e.g., `Europe/Stockholm`, `America/New_York`).
- **VAT & Fees**: Enter your local tax and grid transfer fees (SEK/kWh) to ensure ROI calculations are correct.

---

## 🔗 Part 2: Home Assistant Integration

Darkstar needs "Eyes" and "Hands" to work. Find these in **Settings -> System (HA Section)**.

### 2.1 The "Eyes" (Input Sensors)
Map your existing Home Assistant sensors so Darkstar can see your home status:
- **Battery SoC**: Percentage sensor.
- **PV Power**: Real-time production (Watts or kW).
- **Load Power**: Total home consumption.

### 2.2 The "Hands" (Control Entities)
Darkstar writes to these entities to execute the plan:
- **Work Mode Selector**: The entity that switches your inverter mode.
- **Grid Charging Switch**: Toggles charging from the grid.
- **Current Limits**: Entities to set max Amps for charging/discharging.

---

## 🧪 Part 3: Advanced Tuning (Optimization)

Navigate to **Settings -> Parameters**. This is where you tune the "brain".

### 3.1 Water Heater Strategy
Darkstar optimizes your water heater by shifting consumption to the cheapest hours.
- **Temp: Off/Idle**: The "safety floor" (e.g., 40°C) to prevent legionella while minimizing heat loss.
- **Temp: Normal**: Your target temperature for scheduled hot water (e.g., 60°C).
- **Temp: Boost**: The temperature used when you press "Water Boost" (e.g., 75°C).
- **Min kWh/day**: How much energy your boiler needs daily to keep your family happy.

### 3.2 Forecasting & Safety
- **PV Confidence (%)**: If your solar forecast is often too optimistic, lower this (e.g., 85%) to be safe.
- **Load Safety Margin (%)**: Increase this (>100) if you want the planner to "expect" more load than usual (prevents running out of battery).

### 3.3 Battery Economics
- **Battery Cycle Cost (SEK/kWh)**: The cost of wear-and-tear. If the price difference between "cheap" and "expensive" is less than this cost, Darkstar won't cycle the battery.

---

## ✅ Part 4: Verification Checklist

Once configured, verify the system is working:
1.  **Check Status**: Look at the bottom of the **Sidebar**. The small status dot should be **Green** (Online).
2.  **Verify Sensors**: The "Current SoC" on the Dashboard should match your inverter's real SoC.
3.  **Generate Schedule**: Go to the **Schedule** tab. It might take up to 30 minutes for the first plan to appear. You can also trigger a plan manually by pressing the "Run Planner" button.
4.  **Check Logs**: If no schedule appears, go to **Settings -> Advanced -> Logs** to see if the solver is reporting errors.
5.  **Test Execution**: Enable a manual charge slot and verify that your inverter actually starts charging. You can test this with the top-up button or water heating boost button.

---

## 🕵️ Shadow Mode (The "Safe" Start)

By default, Darkstar might be in **Shadow Mode**. In this mode, the system calculates everything and logs what it *would* have done, but it does **not** change any entities in Home Assistant.

- **To Observe**: Keep `executor.shadow_mode` enabled (found in **Settings -> Advanced**).
- **To Go Live**: Disable `shadow_mode` and ensure `darkstar_enable` (Automation Toggle) is ON in Home Assistant.

> [!WARNING]
> Always monitor the system during the first 24 hours of live execution. Ensure your inverter safety limits are configured correctly in the inverter itself!
