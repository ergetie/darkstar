# Darkstar Configuration Guide

> [!IMPORTANT]
> **HAVE YOU INSTALLED YET?**
> This guide is for *configuring* Darkstar after it is running. If you haven't installed the software yet, please follow the [README.md Installation Steps](https://github.com/ergetie/darkstar/README.md#installation) first.

Welcome to the Darkstar Public Beta! This guide will walk you through tuning your system for maximum savings and safety. All changes should be made via the **Settings** tab in the Darkstar Web UI. You can also directly edit the config.yaml file if you prefer, but that requires a restart of the Darkstar service after changes.

---

## 🛠️ Part 1: The Basics (System & Location)

Navigate to **Settings -> System**. These are the "foundations" of your optimization.

### 1.1 Inverter Profile
The first and most important setting is your **Inverter Profile**. Darkstar uses profiles to automatically configure the correct entities and control logic for your specific hardware.
- **Select Profile**: Choose your brand (e.g., `Deye`, `Fronius`).
- **Generic Profile**: Use this if your brand is not listed. You will need to manually map all entities.
- **Custom Profiles**: If you want to create your own profile, see the **[Profile Creation Guide](CREATING_INVERTER_PROFILES.md)**.

#### Deye / SunSynk: Time of Use program 6
Darkstar writes the battery SoC target directly to **Time of Use program 6 SoC** (default `number.inverter_program_6_soc`). On the inverter:
1. Enable **Time of Use**.
2. Set **all six program times to 00:00**. With every program starting at 00:00, program 6 is the active program all day.

The old setup with an `input_number.master_soc_target` helper and an automation copying it into all six program SoCs is no longer needed. Existing installs keep their configured `soc_target`; only the default and the suggestions changed.

Darkstar checks the six program times (derived from `soc_target`, e.g. `time.inverter_program_1_time` ... `time.inverter_program_6_time`). If any time is not 00:00 you get a health warning. If the times cannot be read (other entity naming, helper entity, or entities missing), onboarding and **Settings -> System** show a "Couldn't verify program times" note you can dismiss.

##### Fallback: master SoC helper
If writing program 6 SoC does not take effect on your model, use the helper setup instead: create an `input_number.master_soc_target` helper (0-100, unit %), set it as `soc_target` in **Settings -> System**, and copy it to all six program SoCs with an automation:

```yaml
alias: Darkstar master SoC to all Deye programs
mode: queued
triggers:
  - trigger: state
    entity_id: input_number.master_soc_target
actions:
  - action: number.set_value
    target:
      entity_id:
        - number.inverter_program_1_soc
        - number.inverter_program_2_soc
        - number.inverter_program_3_soc
        - number.inverter_program_4_soc
        - number.inverter_program_5_soc
        - number.inverter_program_6_soc
    data:
      value: "{{ states('input_number.master_soc_target') | float(0) }}"
```

> [!WARNING]
> **Check Your Units! (Watts vs kW)"
> This is the #1 setup error. Ensure Darkstar knows the correct unit:
> - If your sensor emits **Watts** (e.g., `1500`), ensure your configuration matches (often auto-detected or specified in config).
> - If your sensor emits **Kilowatts** (e.g., `1.5`), ensure units align.
> *Mixing these up will cause the planner to think you have 1000x more power than you do!*

### 1.2 Location & Solar Array
Darkstar uses the **Open-Meteo API** to predict your solar production based on weather forecasts.
- **Latitude / Longitude**: Must be accurate for weather-based forecasting.
- **Solar Arrays**: You can configure up to **6 independent solar arrays** (e.g., South Roof, West Garage).
    - **Azimuth / Tilt**: 180° Azimuth is South. Tilt is the angle of your panels.
    - **Capacity (kWp)**: The peak DC power for each specific array.
Darkstar automatically aggregates these arrays into a single site forecast while accounting for their individual orientations.

### 1.3 Battery Specifications (Hardware Limits)
- **Battery Capacity (kWh)**: The total energy your battery can hold. Darkstar uses this alongside your SoC limits to determine the "usable window".
- **Hardware Limits**: Depending on your inverter, you enter these in **Amperes (A)** or **Watts (W)**. Darkstar automatically converts these to kW for the planning engine.
- **Voltage Duality (A-mode only)**:
    - **Nominal Voltage (V)**: The standard operating voltage (e.g., `48.0` or `51.2`). Used by the **Planner** to forecast energy movement.
    - **Minimum Voltage (V)**: The "safety floor" (e.g., `46.0`). Used by the **Executor** to calculate safety-safe charging currents—ensuring it never pushes more than the battery can handle even at its lowest state.
- **Min/Max SoC (%)**: Your safe operating range (e.g., 12% to 100%). Darkstar will never plan a target outside this range.

### 1.4 Pricing & Timezone
- **Nordpool Price Area**: Your region (e.g., `SE4`, `NO1`, `FI`).
- **Timezone**: Must be in **IANA format** (e.g., `Europe/Stockholm`, `America/New_York`).
- **VAT & Fees**: Enter your local tax and grid transfer fees (SEK/kWh) to ensure ROI calculations are correct.

### 1.5 Smart EV Charging (Optional)
Darkstar can intelligently manage your EV charging to ensure it uses the cheapest power while protecting your house battery.
- **Enable EV Integration**: Set `ev_charger.enabled: true` in **Settings -> System**.
- **Input Sensors**:
    - **EV SoC**: The State of Charge (%) of your vehicle.
    - **Plug Sensor**: A binary sensor indicating if the car is plugged in.
- **Control Entity**:
    - **Switch Entity**: The Home Assistant entity used to start/stop charging (e.g., `switch.my_wallbox`).
- **Safety Parameters**:
    - **Min Target SoC**: The minimum level you want your car to reach (e.g., 40%). Darkstar will prioritize reaching this level as quickly as possible during cheap windows.
    - **Max Power (kW)**: The maximum charging speed of your wallbox.
    - **Battery Capacity (kWh)**: The total size of your EV's battery.

---

## 🔗 Part 2: Home Assistant Integration

Darkstar needs "Eyes" and "Hands" to work. Find these in **Settings -> System (HA Section)**.

### 2.1 The "Eyes" (Input Sensors)
Map your existing Home Assistant sensors so Darkstar can see your home status:
- **Battery SoC**: Percentage sensor.
- **PV Power**: Real-time production (Watts or kW).
- **Load Power**: Total home consumption.

> [!WARNING]
> **Check Your Units! (Watts vs kW)**
> This is the #1 setup error. Ensure Darkstar knows the correct unit:
> - If your sensor emits **Watts** (e.g., `1500`), ensure your configuration matches (often auto-detected or specified in config).
> - If your sensor emits **Kilowatts** (e.g., `1.5`), ensure units align.
> *Mixing these up will cause the planner to think you have 1000x more power than you do!*

### 2.2 The "Hands" (Control Entities)
Darkstar writes to these entities to execute the plan:
- **Work Mode Selector**: The entity that switches your inverter mode. (Automatically configured if using a profile).

> [!TIP]
> **Hardware Cheat Sheet: Common Inverter Mode Strings**
> If you are using the **Generic Profile**, you must provide the exact mode strings. Here are verified strings for popular brands:
> | Brand | Export Mode String | Solar/Self-Use Mode String |
> | :--- | :--- | :--- |
> | **Solis** | `Feed-in Priority` | `Self-Use` |
> | **Deye / SunSynk** | `Export First` | `Zero Export to CT` |
> | **Huawei** | `General Mode` | `Time of Use` |
> | **GoodWe** | `General Mode` | `Eco Mode` |
> | **Fronius** | `Discharge to grid` | `Auto` |
> *Check your inverter integration documentation for exact case-sensitive strings.*
>
> **Deye / SunSynk**: the SoC target goes to Time of Use program 6 SoC, so enable Time of Use and set all six program times to 00:00 (see [1.1 Inverter Profile](#deye--sunsynk-time-of-use-program-6)).
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

## 📚 Next Steps: The User Manual

Configuration is just the start! To learn how to operate Darkstar daily (Quick Actions, Risk Appetite, Dashboard Charts), proceed to the **[Darkstar User Manual](USER_MANUAL.md)**.
