# 📘 Darkstar User Manual

Welcome to **Darkstar**, your AI-powered energy manager.

Unlike traditional "if-this-then-that" automations, Darkstar doesn't follow rigid rules. Instead, it **plans**. It looks 48 hours into the future, considers weather, prices, and your battery's health, and calculates the mathematically optimal path to save you money.

---

## 🚀 1. The Dashboard Explained

The Dashboard is your "Mission Control". Here's how to read it.

### The Horizon Chart
This chart visualizes the 48-hour plan.
*   **Gold Area (☀️)**: Solar Production Forecast.
*   **Cyan Bars (🏠)**: Your Home's Forecasted Load.
*   **Grey Line (📉)**: Electricity Price (Spot + Tax).
*   **Cyan Line (🔋)**: Battery State of Charge (SoC).
    *   **Solid Line**: The *Plan* (what should happen).
    *   **Dotted Line**: The *Actual* (what is happening).
*   **Vertical "NOW" Line**: Everything to the **left** is history. Everything to the **right** is the future plan.

### Visual Color Code
*   **🟢 Green**: **Export**. You are selling energy to the grid.
*   **🔴 Orange**: **Grid Charge**. You are buying energy to charge the battery (usually because it's cheap!).
*   **🌸 Pink**: **Discharge**. You are using battery power to avoid expensive grid prices.
*   **🔵 Blue**: **Water Heating**. Darkstar is heating your hot water tank.

### status Dot (Sidebar)
Look at the small dot at the bottom of the Sidebar (left menu).
*   **🟢 Green**: **Online**. Connected to Home Assistant.
*   **🔴 Red**: **Offline**. Connection lost. Check your HA configuration.
*   **⚫ Grey**: **Connecting**. Waiting for analyzing to complete.

---

## 🧠 2. Deep Dive: Strategy & Risk

Darkstar isn't magic; it's math. You control the math with **Risk Appetite**.

### What is "Risk Appetite"?
Weather forecasts are never 100% perfect. "Risk Appetite" tells Darkstar how much to trust the forecast.

| Level | Name | Philosophy | Safety Buffer |
| :--- | :--- | :--- | :--- |
| **1** | **Safety** | *"I never want to run empty."* | **+35%** added to minimum battery target. |
| **2** | **Conservative** | *"Better safe than sorry."* | **+20%** added buffer. |
| **3** | **Neutral** | *"Trust the math."* | **+10%** standard buffer. |
| **4** | **Aggressive** | *"I want maximum savings."* | **+3%** minimal buffer. |
| **5** | **Gambler** | *"Live dangerously."* | **-7%**. Intentionally targets *below* minimum, betting on a replan/extra PV/Lower load. |

**Example**:
If your `Min SoC` is 10%, and you choose **Level 1 (Safety)**, Darkstar will aim to keep your battery at **45%** (10% + 35%) before the sun comes up, just in case the forecast is wrong.
If you choose **Level 5 (Gambler)**, it might let you drop to **3%**, betting that the sun *will* shine.

### The "S-Index" (Strategic Index)
You'll see an "S-Index" score on the dashboard. This measures **volatility**.
*   **1.0**: Normal day.
*   **> 1.0**: High uncertainty (variable clouds, price spikes). Darkstar will be more conservative.
*   **< 1.0**: Stable, predictable day.

---

## 🎮 3. Operations & Controls

### Quick Actions (Executor Tab)
*   **Force Charge**: Immediately charges the battery to 100% (or your set limit) at max power. Useful if a storm is coming.
*   **Pause Plan**: Stops all automated control. Your battery will sit idle.
*   **Water Boost**: Triggers the water heater immediately, ignoring price. Useful if you need a hot bath *now*.

### Water Heating Comfort
In **Settings -> Parameters**, you can set the Water Heater "Comfort Level".
*   **Economy**: ONLY heats when prices are rock bottom. You might have lukewarm water.
*   **Balanced**: Good mix of savings and comfort.
*   **Priority/Lux**: Heats whenever the tank temp drops, mostly ignoring price.

### Shadow Mode
In **Settings -> Advanced**, you can enable **Shadow Mode**.
*   **ON**: Darkstar calculates the plan but **DOES NOT** send commands to your inverter. It just watches. Great for testing.
*   **OFF**: Darkstar has full control.

---

## ⚠️ 4. Troubleshooting

### "Why isn't it charging?"
1.  **Check Risk Appetite**: If you are on "Level 5 (Gambler)", it might be waiting for an even cheaper price later.
2.  **Check Prices**: Is the price actually low? Darkstar factors in "Cycle Cost". If (Price difference < Cycle Cost), it won't cycle the battery.
3.  **Check Constraints**: Is the battery already full? Is the inverter maxed out?

### "My battery is draining into the grid!"
*   Check your **Home Assistant export settings**. Darkstar usually sets "Self-Use" or "Zero Export", but if your inverter is in "Selling First" mode manually, it will dump energy.

### "The plan keeps changing!"
*   This is normal. Darkstar replans every time new data comes in (weather updates, new prices). It's constantly course-correcting, like a GPS avoiding traffic.
