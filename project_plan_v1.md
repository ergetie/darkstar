# Project Plan: Helios Energy Manager in Python

## 1. Project Goal

The primary goal is to implement the core scheduling logic of the Helios Energy Manager (based on v6.2 and v6.3 documents) in Python. The system will ingest energy market data and forecasts to generate an optimal 24-47 hour battery and water heating schedule.

This initial phase focuses on creating a `planner` that produces a `schedule.json` file. The integration with live data sources and the real-time `executor` are subsequent steps.

## 2. Proposed Architecture & File Structure

The project will be organized into the following files, ensuring a clear separation of concerns:

```
helios_project/
│
├── config.yaml               # All user-configurable parameters and thresholds.
├── inputs.py                 # (Placeholder) Functions for fetching external data.
├── planner.py                # Core MPC logic for generating the schedule.
├── executor.py               # (Placeholder) Reads the schedule and executes the current action.
└── schedule.json             # Output of the planner; a time-slotted plan of actions.
```

## 3. Component Details

### 3.1. `config.yaml` - Configuration File

This file will store all system parameters to allow for easy tuning without code changes. It should be structured logically.

**Content:**
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
  battery_use_margin_sek: 0.10      # Use battery if grid > battery_cost + margin
  export_profit_margin_sek: 0.20    # Export if export_price > battery_cost + margin
  battery_water_margin_sek: 0.20    # Margin for using battery for water heating

# Charging Strategy
charging_strategy:
  charge_threshold_percentile: 15   # Bottom 15% of prices are considered 'cheap'
  cheap_price_tolerance_sek: 0.10   # Extends 'cheap' category to prices within this tolerance

# Strategic Charging (Floor Price)
strategic_charging:
  price_threshold_sek: 0.90         # Price below which strategic charging is triggered
  target_soc_percent: 95            # Absolute SoC target for strategic charging

# Water Heating
water_heating:
  power_kw: 3.0                     # Power consumption of the water heater
  daily_duration_hours: 2.0         # Required heating duration per 24 hours

# Safety and Buffers
safety:
  s_index_factor_base: 1.05         # Base safety buffer for load forecasts
```

### 3.2. `inputs.py` - Data Abstraction Layer

This file will contain placeholder functions responsible for fetching all necessary data. For this initial phase, these functions can return hardcoded, sample data for testing the planner.

**Key Functions:**
*   `get_nordpool_data(timezone)`: Returns a list of dictionaries with `start_time`, `end_time`, `import_price_sek`, `export_price_sek`.
*   `get_forecast_data(timezone)`: Returns PV and Load forecasts for the planning horizon.
*   `get_initial_state()`: Returns the current state, including `battery_soc_percent` and `battery_cost_sek_per_kwh`.

### 3.3. `planner.py` - The Core Scheduler

This is the central component. It will contain a `HeliosPlanner` class that ingests configuration and input data to produce the schedule. The core logic should follow the multi-pass approach described in the Helios v6.2/6.3 documents.

**Class Structure:**
```python
import pandas as pd
import yaml

class HeliosPlanner:
    def __init__(self, config_path):
        # Load config from YAML
        # Initialize internal state

    def generate_schedule(self, input_data):
        # The main method that executes all planning passes and returns the schedule.
        pass

    # Private methods for each pass of the MPC logic
    def _prepare_data_frame(self, input_data):
        # Create a timezone-aware pandas DataFrame indexed by time for the planning horizon.
        # Columns: import_price, export_price, pv_forecast_kwh, load_forecast_kwh, etc.
        pass

    def _pass_1_identify_windows(self, df):
        # Calculate price percentiles and apply cheap_price_tolerance_sek.
        # Identify and group consecutive cheap slots into charging 'windows'.
        # Detect if a strategic period is active (PV forecast < Load forecast).
        pass

    def _pass_2_schedule_water_heating(self, df):
        # Find the cheapest slots for the required daily duration and assign water heating action.
        pass
        
    def _pass_3_simulate_baseline_depletion(self, df):
        # Simulate battery SoC evolution assuming no grid charging, only covering load.
        # This determines the state of the battery at the start of each charging window.
        pass

    def _pass_4_allocate_cascading_responsibilities(self, df, windows):
        # This is the core MPC logic.
        # For each window, calculate the energy 'gap' needed before the next window.
        # Use a projected minimum battery cost for the calculation.
        # Implement 'Cascading Responsibility': if a future window cannot cover its own gap, the current window must inherit that responsibility.
        # Implement 'Strategic Override': If a window is in a strategic period, its target is an absolute SoC (e.g., 95%), not gap-based.
        # Use 'Realistic Capacity Estimation' to determine how much a window can actually charge, accounting for inverter limits and concurrent loads (water heating).
        pass
        
    def _pass_5_distribute_charging_in_windows(self, df, windows):
        # For each window, sort the slots by price.
        # Iteratively assign 'Charge' action to the cheapest slots until the window's total charging responsibility (in kWh) is met.
        pass
        
    def _pass_6_finalize_schedule(self, df):
        # Generate the final schedule.
        # For each slot, determine the final action:
        # 1. Water_Heating (if scheduled)
        # 2. Charge (if scheduled)
        # 3. Export (if profitable arbitrage opportunity exists)
        # 4. Discharge (if grid_price > battery_cost + margin)
        # 5. Hold (preserve battery, especially in non-charging cheap slots or when costs are close)
        # Handle PV surplus: any excess PV must be used to charge the battery.
        pass
```

### 3.4. `schedule.json` - The Output Plan

The planner must produce a JSON file containing a list of hourly slots. This file is the "contract" between the planner and executor.

**Schema Definition and Example:**
Each object in the list represents a one-hour time slot.
```json
[
  {
    "slot_start": "2025-10-28T14:00:00+01:00",
    "slot_end": "2025-10-28T15:00:00+01:00",
    "classification": "Discharge",
    "import_price_sek_kwh": 1.85,
    "export_price_sek_kwh": 1.75,
    "charge_kw": 0.0,
    "discharge_kw": 2.5,
    "grid_import_kw": 0.0,
    "grid_export_kw": 0.0,
    "water_heating_kw": 0.0,
    "soc_target_percent": 15.0,
    "projected_soc_percent": 65.5,
    "projected_battery_cost_sek_kwh": 1.22
  },
  {
    "slot_start": "2025-10-28T23:00:00+01:00",
    "slot_end": "2025-10-29T00:00:00+01:00",
    "classification": "Charge",
    "import_price_sek_kwh": 0.88,
    "export_price_sek_kwh": 0.80,
    "charge_kw": 5.0,
    "discharge_kw": 0.0,
    "grid_import_kw": 5.0,
    "grid_export_kw": 0.0,
    "water_heating_kw": 0.0,
    "soc_target_percent": 95.0,
    "projected_soc_percent": 82.1,
    "projected_battery_cost_sek_kwh": 1.15
  }
]
```

## 4. Implementation Priorities (Core Logic from Documents)

The AI must prioritize implementing the following validated concepts from the Helios v6.2 and v6.3 documents:

1.  **Multi-Pass Planning:** The `generate_schedule` method must follow the logical passes outlined above.
2.  **Strategic Charging:** Implement the logic where `PV forecast < Load forecast` and `price < strategic_price_threshold_sek` triggers charging to an absolute `strategic_target_soc_percent`.
3.  **Cascading Window Responsibility:** This is critical. A charging window must calculate the needs of the *next* period and charge for it proactively if the next window is insufficient.
4.  **Integrated Water Heating:** Water heating decisions must be made within the planner (Pass 2) to ensure its load is accounted for in subsequent capacity calculations.
5.  **Hold in Cheap Windows:** In a cheap window, slots that are not used for charging should be set to 'Hold', preventing the battery from discharging to cover load when prices are low.
6.  **Realistic Capacity Estimation:** When determining how much a window can charge, the calculation must subtract the average power consumed by other appliances (like the water heater).
7.  **Projected Cost Calculation:** Use the window's *cheapest* price to pre-calculate a minimum projected battery cost. This cost should be used for threshold decisions during planning.

## 5. Out of Scope for this Phase

The following features from the documentation should **not** be implemented at this stage:

*   The `Learning Engine`, `Forecast Adjuster`, and `S-Index Calculator`. A simple static buffer factor (`s_index_factor_base`) should be used for now.
*   Database integration (`DB Writer`, `execution_history`). The JSON file is the only required output.
*   The `RT Executor` (`executor.py`). A placeholder file is sufficient.
*   Advanced features from the backlog (e.g., dynamic thresholds, multi-day planning).
