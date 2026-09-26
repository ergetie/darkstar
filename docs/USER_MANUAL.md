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

| Level | Name             | Philosophy                     | Overnight safety floor                                                     |
| :---- | :--------------- | :----------------------------- | :------------------------------------------------------------------------- |
| **1** | **Safety**       | *"I never want to run empty."* | At least **25%** of capacity above min SoC, **+30%** margin on the deficit. |
| **2** | **Conservative** | *"Better safe than sorry."*    | At least **15%** above min SoC, **+20%** margin.                            |
| **3** | **Neutral**      | *"Trust the math."*            | At least **10%** above min SoC, **+15%** margin.                            |
| **4** | **Aggressive**   | *"I want maximum savings."*    | At least **3%** above min SoC, **+5%** margin.                              |
| **5** | **Gambler**      | *"Live dangerously."*          | No extra reserve: the floor can go down to min SoC, but never below it.     |

The safety floor is the energy Darkstar keeps in the battery to cover the forecast shortfall (load minus solar) until the next cheap or sunny period. The margin is added on top of that forecast shortfall; the minimum reserve applies even when no shortfall is forecast. Cold or unsettled weather adds a little extra, and the total extra is capped by `max_safety_buffer_percent` (scaled per level).

**Example**: with a 20 kWh battery, `Min SoC` 10% and no forecast shortfall, **Safety** keeps at least 35% (10% + 25%) overnight, while **Gambler** lets the battery go down to 10%.

In the dashboard, tap **Risk** in the command bar to pick a level.

### The "S-Index" (Strategic Index)
You'll see an "S-Index" score on the dashboard. This measures **volatility**.
*   **1.0**: Normal day.
*   **> 1.0**: High uncertainty (variable clouds, price spikes). Darkstar will be more conservative.
*   **< 1.0**: Stable, predictable day.

---

## 🎮 3. Operations & Controls

### Quick Actions (Executor Tab)
*   **Dynamic Monitoring**: All logs and charts in the Executor tab automatically respect your hardware's native units (**Amperes** or **Watts**).
*   **Top Up (Force Charge)**: Charges the house battery now, at max power, until it reaches the target SoC you pick. It then stops and Darkstar follows the plan again. Tap **Top Up** in the command bar, pick a preset (40/60/80/100%) or set a custom target with **−/+** (15% steps) or by typing, then press **Start**. The target can't be below your `min_soc_percent` or at/below the battery's current SoC. It stops early if you open Top Up and press **Stop Top Up**, and after 24 hours at the latest. Useful if a storm is coming.
*   **EV Charge**: Charges your car now until it reaches a target SoC — see [Charge now](#charge-now-manual-ev-charge) below.
*   **Pause Plan**: Stops all automated control. Your battery will sit idle.
*   **Water Boost**: Triggers the water heater immediately, ignoring price, for 30 minutes, 1 hour, 2 hours or a custom length (15 minutes to 6 hours, in 15-minute steps). Useful if you need a hot bath *now*.
*   **Vacation**: Pauses normal water heating for a number of days (presets or a custom number). Only the periodic anti-legionella cycle still runs.

### Water Heating Comfort
In the dashboard, tap **Water** in the command bar to set the Water Heater "Comfort Level" (1-5).

The comfort level controls **two key parameters**:
1. **Window Size** - How long each heating session can be
2. **Penalties** - How strictly the system enforces these windows

**Comfort Levels:**
- **Level 1 (Economy)**: Large windows (4h+) = bulk heating in cheapest periods. May have lukewarm water between sessions.
- **Level 2 (Balanced)**: Moderate windows (2.7h) = good mix of savings and comfort.
- **Level 3 (Neutral)**: Baseline windows (2.1h) = slight preference for spacing.
- **Level 4 (Priority)**: Small windows (1.3h) = more frequent heating throughout the day.
- **Level 5 (Maximum)**: Tiny windows (0.7h) = very frequent heating = most stable temperature.

**Bulk Mode Override:**
Set `enable_top_ups: false` in config to force single-block bulk heating regardless of comfort level. This preserves reliability penalties but allows one large heating session per day.

### Shadow Mode
In **Settings -> Advanced**, you can enable **Shadow Mode**.
*   **ON**: Darkstar calculates the plan but **DOES NOT** send commands to your inverter. It just watches. Great for testing.
*   **OFF**: Darkstar has full control.

---

## 🔋 4. Smart EV Charging Strategy

Darkstar treats your Electric Vehicle as a "Deferrable Load." This means it understands the car needs a certain amount of energy but can wait for the most optimal time to get it.

### How it Works
1.  **Plug-in Detection**: When you plug in your car, Darkstar detects the change and immediately triggers a **Re-plan**. It calculates how much energy you need to reach your `Min Target SoC`.
2.  **Source Isolation**: Darkstar ensures your house battery is **protected**. It will only charge the car using Solar Surplus or cheap Grid power. It will *not* discharge your house battery into the EV.
3.  **The Priority System**: Darkstar uses dynamic pricing "penalties" based on your car's SoC:
    *   🔴 **Emergency (<20%)**: Charges immediately at any price.
    *   🟡 **High Priority (20-40%)**: Prioritizes charging in the next available cheap windows.
    *   🟢 **Normal (>40%)**: Only charges when prices are at their absolute lowest.

### Charge now (manual EV charge)
Use **EV Charge** in the dashboard command bar when you want the car charged *now*, regardless of the plan.

*   The control appears when a car is plugged into a charger Darkstar controls. With several cars plugged in, pick the charger first.
*   Tap **EV**, pick a preset (40/60/80/100%) or a custom target with **−/+** (15% steps) or by typing (1–100%), then press **Start charging**.
*   **Current-type chargers** charge at the charger's `max_current_a`. Choose a lower current under **Charging current** in the EV popover. **Binary chargers** are simply switched on.
*   The fuse/load balancer still applies: it may throttle or pause the car to protect your main fuse. A **Pause**, the **manual override**, or a **Force Stop** still stop charging.
*   It ends by itself when the car reaches the target, when you unplug, when you press **Stop** (command bar EV popover or EV card), or after 24 hours. Darkstar then replans and goes back to the plan.
*   It does **not** change your charging goal (target SoC / ready-by). It survives a restart.
*   The request is refused if the car isn't connected, its SoC is unknown, or it is already at the target. Requires `soc_sensor` (and ideally `plug_sensor`) on the charger.
*   The car's SoC sensor often updates only every few minutes, so the car may end a few percent above the target.

### Dashboard Indicators
*   **Gold Bars**: EV charging power is shown on the Dashboard and Horizon chart.
*   **EV SoC**: Your car's current charge level is displayed in the Charging Status card. An active manual charge shows as "Manual charge → 80% · Stop".
*   **Power-flow EV node** (one charger): a violet ⚡ + `49% → 80%` while charging (target = manual charge target, else your goal), a green 🔌 + `49%` when plugged in but idle (the same green the EV popup uses for a connected car), and a greyed unplug icon with "away" when no car is connected. The node stays at full brightness whenever a car is connected, even at 0 kW, so "connected but waiting for cheap power" is easy to tell apart from "away"; only with no car connected is it dimmed like other idle nodes. With several chargers it shows the icon for the "busiest" state and "N connected". Tap it for per-car SoC and target.

---

## ⚠️ 5. Troubleshooting

### "Why isn't it charging?"
1.  **Check Risk Appetite**: If you are on "Level 5 (Gambler)", it might be waiting for an even cheaper price later.
2.  **Check Prices**: Is the price actually low? Darkstar factors in "Cycle Cost". If (Price difference < Cycle Cost), it won't cycle the battery.
3.  **Check Constraints**: Is the battery already full? Is the inverter maxed out?

### "My battery is draining into the grid!"
*   Check your **Home Assistant export settings**. Darkstar usually sets "Self-Use" or "Zero Export", but if your inverter is in "Selling First" mode manually, it will dump energy.

### "The plan keeps changing!"
*   This is normal. Darkstar replans every time new data comes in (weather updates, new prices). It's constantly course-correcting, like a GPS avoiding traffic.

---

## ⚠️ Safety Considerations

### Battery State of Charge (SoC) Limits

**Darkstar's `min_soc_percent` is NOT a safety limit.** It is a planning constraint used by the optimization algorithm to determine charge/discharge schedules.

- **Planning Constraint**: The planner uses `min_soc_percent` to calculate optimal schedules
- **Not a Hard Floor**: The executor will NOT force charging if the battery drops below this value
- **BMS Responsibility**: Your battery's **BMS (Battery Management System)** must handle the actual hard safety cutoff

**⚠️ WARNING:**
- If your inverter/BMS allows discharge below safe levels, Darkstar will not prevent it
- Ensure your inverter is configured with appropriate hard SoC limits
- Verify your battery BMS has a hard cutoff configured to prevent over-discharge
- Without proper BMS limits, deep discharge could damage your battery

**Recommended Actions:**
1. Check your inverter settings for minimum SoC limits
2. Ensure the BMS hard limit is below Darkstar's `min_soc_percent`
3. Test that your BMS actually cuts off discharge at the configured limit
4. Monitor battery behavior during initial use to verify safety limits work

---

## 📚 6. FAQ

### "Executor not setting entity" - How to check history logs

Some inverter profiles (like Sungrow) require setting **multiple entities** to achieve a specific mode. For example, "Charge from Grid" might require:
- Setting the work mode to "Forced Charge"
- Setting an EMS mode switch to "Forced Mode"
- Setting a forced charge/discharge command to "Charge"
- Setting an export power limit to 0

**How to verify what the executor is doing:**

1. **Go to the Executor tab** in the Darkstar dashboard
2. **Find the execution record** for the time when the mode should have changed
3. **Expand the record** (click on it) to see detailed action results
4. **Look for composite mode actions** - these are shown as sub-items of the main mode change
5. **Check each entity change**:
   - ✅ **Green check**: Entity was set successfully
   - ❌ **Red X**: Entity set failed (shows error message)

**Common issues:**
- **Wrong entity ID**: The entity doesn't exist in Home Assistant
- **Permission denied**: Darkstar's Home Assistant token doesn't have write access
- **Invalid value**: The value you're trying to set isn't accepted by the inverter
- **Read-only entity**: Some integrations expose entities as read-only

**What to do:**
1. Check the Executor history for specific error messages
2. Verify entity IDs match your Home Assistant setup
3. Check inverter profile configuration in Settings
4. Test the entity manually in Home Assistant Developer Tools to confirm it's writable
