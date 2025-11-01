# OUTDATED! SEE IMPLEMENTATION_PLAN.MD!

# Master Project Plan: darkstar Energy Manager (Python Implementation)
**Version: 3.0 (Authoritative)**

## 1. Project Goal

The primary goal is to implement the core scheduling logic of the Helios Energy Manager in Python, based on the advanced, multi-pass MPC logic from the v6.3 JavaScript reference implementation. The system will ingest real-world energy market data and forecasts to generate an optimal 24-47 hour battery and water heating schedule, which will be saved to a `schedule.json` file.

## 2. Architecture & File Structure

The architecture is designed for clarity, testability, and separation of concerns.

```
helios_project/
│
├── config.yaml               # All user-configurable parameters and thresholds.
├── inputs.py                 # Handles all external data fetching and preparation.
├── planner.py                # Core MPC logic for generating the schedule.
├── executor.py               # (Placeholder) Reads the schedule and executes actions.
└── schedule.json             # The final output: a time-slotted plan of actions.
```

## 3. Component Details

### 3.1. `config.yaml` - The Master Configuration File

This file stores all system parameters.

```yaml
# General System Settings
timezone: "Europe/Stockholm"

# Battery Specifications
battery:
  capacity_kwh: 10.0
  min_soc_percent: 15
  max_soc_percent: 95
  max_charge_power_kw: 5.0
  max_discharge_power_kw: 5.0
  efficiency_percent: 95.0

# Decision Making Thresholds
decision_thresholds:
  battery_use_margin_sek: 0.10
  battery_water_margin_sek: 0.20
  export_profit_margin_sek: 0.20

# Charging Strategy
charging_strategy:
  charge_threshold_percentile: 15
  cheap_price_tolerance_sek: 0.10

# Strategic Charging (Floor Price)
strategic_charging:
  price_threshold_sek: 0.90
  target_soc_percent: 95

# Water Heating
water_heating:
  power_kw: 3.0
  daily_duration_hours: 2.0

# Forecasting Safety Margins
forecasting:
  pv_confidence_percent: 90.0
  load_safety_margin_percent: 110.0

# Nordpool API Configuration
nordpool:
  price_area: "SE4"
  currency: "SEK"
  resolution_minutes: 15

# Electricity Pricing & Fees
pricing:
  vat_percent: 25.0
  grid_transfer_fee_sek: 0.2456
  energy_tax_sek: 0.439
```

### 3.2. `inputs.py` - The Data Abstraction Layer

This module is responsible for fetching and preparing all necessary external data.

*   **`get_nordpool_data()`:** Fetches real price data for both today and tomorrow from the Nordpool API, using the configurable resolution (e.g., 15 minutes). It correctly handles timezones and applies the complex pricing logic (fees, taxes, VAT) from the config to calculate the final `import_price_sek_kwh` and `export_price_sek_kwh`.
*   **`get_forecast_data()`:** (Currently Placeholder) Generates realistic sample PV and load forecasts for the planning horizon.
*   **`get_initial_state()`:** (Currently Placeholder) Provides a sample starting state for the battery (SoC, cost, etc.).
*   **`get_all_input_data()`:** The main function that orchestrates all calls and returns a single, clean dictionary containing all the data required by the planner.

### 3.3. `planner.py` - The Core Scheduler

This is the "brain" of the system. The `HeliosPlanner` class executes a series of logical passes to build the optimal schedule.

**MPC Pass Logic:**

1.  **`_pass_0_apply_safety_margins(self, df)`:**
    *   The very first step after data preparation.
    *   Applies the `pv_confidence_percent` and `load_safety_margin_percent` from the config to the raw forecasts.
    *   Creates `adjusted_pv_kwh` and `adjusted_load_kwh` columns.
    *   **All subsequent passes MUST use these "adjusted" columns.**

2.  **`_pass_1_identify_windows(self, df)`:**
    *   Implements the intelligent two-step logic for identifying cheap slots:
        1.  Finds an initial set of slots strictly below the percentile threshold.
        2.  Finds the maximum price within that set and adds the `cheap_price_tolerance_sek`.
        3.  Uses this final, robust threshold to define the `is_cheap` column.
    *   Also calculates `is_strategic_period` based on total adjusted PV vs. load.

3.  **`_pass_2_schedule_water_heating(self, df)`:**
    *   Schedules the required daily water heating in the absolute cheapest slots available in the **entire future planning horizon**.
    *   Includes logic to schedule for tomorrow if today's heating is already complete.
    *   Contains the logic to dynamically choose the energy source (PV > Battery > Grid) based on cost margins.

4.  **`_pass_3_simulate_baseline_depletion(self, df)`:**
    *   Simulates the battery's state of charge over the planning horizon assuming **no grid charging**.
    *   This simulation uses the `adjusted` forecasts and accounts for the scheduled water heating load to create a realistic "worst-case" baseline.

5.  **`_pass_4_allocate_cascading_responsibilities(self, df)`:**
    *   The core of the MPC. Calculates the charging `total_responsibility_kwh` for each cheap window.
    *   Must be implemented with the advanced features from the reference code:
        *   **Projected Battery Cost:** Pre-calculates a future minimum battery cost to make more intelligent decisions about future energy gaps.
        *   **Realistic Capacity Estimation:** Estimates a window's true charging capacity by subtracting power that will be consumed by water heating and the average household load during that window.
        *   **Strategic Carry-Forward:** If a strategic charge does not reach its target in one window, it flags the next window to continue charging.

6.  **`_pass_5_distribute_charging_in_windows(self, df)`:**
    *   Takes the responsibilities calculated in Pass 4 and assigns `charge_kw` to the cheapest slots within each respective window until the responsibility is met.

7.  **`_pass_6_finalize_schedule(self, df)`:**
    *   Performs the final, detailed simulation of the battery's state based on the complete plan.
    *   Implements the rich decision hierarchy from the reference code:
        *   **Crucially, it must enforce the "Hold in Cheap Windows" principle**, where the battery is not discharged for load during cheap periods to preserve energy for expensive periods.
        *   It assigns the final action `classification` for each slot (e.g., 'Charge', 'Discharge', 'Hold', 'pv_charge').
        *   It calculates and stores the `projected_soc_kwh` and `projected_battery_cost` for each slot.

8.  **`_save_schedule_to_json(self, df)`:**
    *   The final step. Converts the completed DataFrame into the specified JSON format.
    *   Adds a `slot_number`, renames columns to match the schema, and rounds numerical values to 2 decimal places for clean output.

### 3.4. `schedule.json` - The Output Plan Schema

The planner's output is a JSON file containing a single key, `schedule`, which is a list of slot objects.

**Example Slot:**
```json
{
  "slot_number": 1,
  "start_time": "2025-10-30T00:00:00+01:00",
  "end_time": "2025-10-30T00:15:00+01:00",
  "import_price_sek_kwh": 1.71,
  "export_price_sek_kwh": 0.69,
  "pv_forecast_kwh": 0.00,
  "load_forecast_kwh": 0.50,
  "classification": "Discharge",
  "battery_charge_kw": 0.00,
  "projected_soc_kwh": 4.00,
  "projected_battery_cost": 1.50
}
```

## 4. Our Refactoring Roadmap

This is our active checklist for upgrading the `planner.py` script to meet the full specification.

- [x] **Fix Rounding:** Adjust `_save_schedule_to_json` to round to 2 decimal places. *(DONE)*
- [x] **Refactor `_pass_1_identify_windows`:** Implement the two-step percentile/tolerance logic. *(DONE)*
- [ ] **Implement `_pass_0_apply_safety_margins`:** Create this new pass to centralize forecast adjustments.
- [ ] **Refactor `_pass_2_schedule_water_heating`:** Implement advanced logic for future-day scheduling and dynamic source selection.
- [ ] **Refactor `_pass_3_simulate_baseline_depletion`:** Update to use adjusted forecasts.
- [ ] **Refactor `_pass_4_allocate_cascading_responsibilities`:** Implement Projected Cost, Realistic Capacity, and Strategic Carry-Forward.
- [ ] **Refactor `_pass_6_finalize_schedule`:** Implement "Hold in Cheap Windows" and richer decision logic.

---
