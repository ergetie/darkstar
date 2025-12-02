# Legacy MPC Planner (Helios/Antares)

**Note:** This document describes the legacy heuristic MPC logic. The system has transitioned to the **Kepler (MILP)** solver as the primary planner. See [architecture.md](architecture.md) for the current architecture.

## The Planner (The Optimizer)

Located in `planner.py`, the core MPC logic executes in **7 logical passes** to build the schedule:

1.  **Pass 0: Apply Safety Margins**: Ingests forecasts (from Aurora or Baseline) and applies confidence margins.
2.  **Pass 1: Identify Windows**: Identifies "Cheap" and "Expensive" price windows relative to the daily average.
3.  **Pass 2: Schedule Water Heating**: Allocates the cheapest slots for water heating to meet daily energy quotas.
4.  **Pass 3: Simulate Baseline**: Simulates battery depletion based on load to find "Must Charge" gaps.
5.  **Pass 4: Allocate Cascading Responsibilities**: The core logic. Cheap windows accept responsibility for future deficits.
    *   *Strategy Injection*: The Strategy Engine inserts dynamic overrides here (e.g., boosting targets).
6.  **Pass 5: Distribute Charging**: Assigns power to specific slots, consolidating blocks to minimize battery cycling.
7.  **Pass 6: Finalize & Hold**: Enforces the **"Hold in Cheap Windows"** principle—preventing the battery from discharging during cheap times to save energy for peak prices.

## Key Logic Details

### Water Heating Scheduler
The planner treats water heating as a flexible load that must meet a daily quota.
*   **Sources**: It checks the Home Assistant sensor (`water_heater_daily_entity_id`). If `min_kwh_per_day` is already met, no slots are scheduled.
*   **Optimization**: If more energy is needed, it picks the absolute cheapest contiguous blocks in the next 24h.
*   **Grid vs. Battery**: In cheap windows, water is heated from the **grid** (not battery) to preserve stored energy for expensive periods.

### Strategic Battery Control
*   **Cascading Responsibility**: A cheap window at 02:00 will charge enough to cover a deficit at 18:00.
*   **Hold Logic**: If prices are low (e.g., 13:00), the battery will **hold** its charge (idle) rather than covering load, because that energy is worth more at 19:00.
*   **S-Index (Safety Factor)**: A dynamic multiplier applied to charging targets based on solar uncertainty.
*   **Cross-Day Responsibility (Rev 60)**: Cheap windows are expanded based on future (today+tomorrow) net deficits and price levels so the planner charges in the cheapest remaining hours and preserves SoC for tomorrow’s high-price periods, even when the battery is already near its target at runtime.
