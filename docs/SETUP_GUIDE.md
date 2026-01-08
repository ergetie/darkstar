# Darkstar Setup Guide

Welcome to the Darkstar Public Beta! This guide will walk you through setting up your energy management system using the Dashboard UI.

## � Step 1: Deployment & First Boot

### Option 1: Home Assistant Add-on (Recommended)
1.  **Add Repository**: Click the "Add Repository" button in the README or manually add `https://github.com/ergetie/darkstar` to your HA Add-on store.
2.  **Install**: Install "Darkstar Energy Manager".
3.  **Configure Add-on Settings**: Before starting, go to the add-on's **Configuration** tab and set:
    - **timezone**: Your IANA timezone (e.g., `Europe/Stockholm`, `America/New_York`).
    - **log_level**: Set to `info` for normal use, or `debug` for troubleshooting.
4.  **Start**: Click **Start**.
5.  **Auto-Config**: Darkstar will **automatically detect** your Home Assistant connection and create its own authentication token. No manual YAML editing is required for the connection!
6.  **Open Dashboard**: Click "Open Web UI" or use the Home Assistant sidebar link. All other settings (entities, battery, solar, etc.) are configured via the Darkstar web UI.

### Option 2: Docker Compose (Standalone)
1.  On your host machine, ensure you have a `config.yaml` and `secrets.yaml`. (Copying the `.default` and `.example` templates is the easiest way to start).
2.  In `secrets.yaml`, you **must** provide your Home Assistant `url` and `token`.
3.  Run `docker-compose up -d`.
4.  Access the UI at `http://<your-ip>:5000`.

---

## 🛠️ Step 2: Configuration (via Settings UI)

Once Darkstar is running, navigate to the **Settings** tab in the Dashboard. Most parameters can be tuned directly in the UI.

### 2.1 System Location
Verify your **Timezone** and **Coordinates**. 
> [!IMPORTANT]
> Accurate Latitude and Longitude are required for solar production forecasting.

### 2.2 Entity Mapping
Find the **Input Sensors** section. Paste your Home Assistant entity IDs into the corresponding fields. You can find these IDs in HA under **Settings -> Devices & Services -> Entities**.
- **Battery SoC**: Percentage sensor (e.g., `sensor.battery_soc`)
- **PV Power**: Current solar production power (W or kW).
- **Load Power**: Your home's total real-time consumption.

### 2.3 Battery Parameters
Define your battery's physical limits so the planner stays within safe bounds:
- **Capacity (kWh)**: The total usable energy storage of your battery bank.
- **Min SoC**: The safe floor (e.g., 15%) that the planner will never discharge below.
- **Max Charge/Discharge (kW)**: The power limits for your inverter.

---

## ✅ Step 3: Verification

1.  Navigate to the **Dashboard** home page.
2.  Check the **Status** card. It should show:
    - **Healthy**: Successful connection to Home Assistant.
    - **Current SoC**: Should match your real battery level.
3.  View the **Schedule** tab. Within 10 minutes, the first generated 48-hour plan should appear, showing the optimized slots for the next two days.

---

## 🆘 Troubleshooting
If you don't see a schedule:
- Ensure your `timezone` matches your Home Assistant system timezone.
- Verify that your sensors provide numeric values in the Home Assistant **Developer Tools -> States** page.
- Check the **Logs** tab in the Dashboard for specific error messages (e.g., "Solver failed to find optimal solution").
