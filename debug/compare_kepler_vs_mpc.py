import argparse
import pandas as pd
from datetime import datetime, date
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from archive.legacy_mpc import HeliosPlanner
from ml.simulation.data_loader import SimulationDataLoader
from backend.kepler.solver import KeplerSolver
from backend.kepler.adapter import planner_to_kepler_input, config_to_kepler_config, kepler_result_to_dataframe

def main():
    parser = argparse.ArgumentParser(description="Compare Kepler vs MPC for a specific day")
    parser.add_argument("--day", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    target_day = datetime.fromisoformat(args.day).date()
    print(f"Running comparison for {target_day}...")

    # Load Data
    loader = SimulationDataLoader(config_path=args.config)
    # We need to simulate the "now" as the start of the day to get the full day plan
    # But wait, the planner usually runs rolling. 
    # If we want to compare a full day schedule, we should probably run it at 00:00 of that day.
    
    start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))
    
    # Get input data for the planner
    # SimulationDataLoader has methods to prepare input_data for a specific time
    # But we might need to use `loader.get_planner_input(start_dt)` if it exists, 
    # or manually construct it using `loader.load_day_data`.
    
    # Let's look at how `bin/run_simulation.py` does it.
    # It calls `loader.build_planner_input(current_time)`.
    
    # input_data = loader.build_planner_input(start_dt)
    input_data = loader.get_window_inputs(start_dt)
    input_data["initial_state"] = loader.get_initial_state_from_history(start_dt)
    
    # DEBUG: Check Input Data Quality
    print("\n--- Input Data Check ---")
    print(f"Initial SoC: {input_data['initial_state'].get('battery_kwh', 'N/A')} kWh")
    
    # Check Forecasts
    if "daily_load_forecast" in input_data:
        print(f"Daily Load Forecast: {input_data['daily_load_forecast']}")
    
    # Check DataFrame content (prices, forecasts)
    # We need to peek at what loader.get_window_inputs returns. 
    # It returns a dict, but usually contains 'nordpool_prices', 'pv_forecast', etc.
    # Wait, get_window_inputs returns a dict with keys like 'nordpool_prices', 'weather_forecast', etc.
    # It does NOT return a DataFrame directly. The planner builds it.
    
    # Let's inspect the raw lists/dicts
    prices = input_data.get("price_data", [])
    if prices:
        avg_price = sum(p["import_price_sek_kwh"] for p in prices) / len(prices)
        print(f"Nordpool Prices: {len(prices)} slots, Avg: {avg_price:.2f} SEK/kWh")
    else:
        print("⚠️ Nordpool Prices: MISSING")
        
    forecasts = input_data.get("forecast_data", [])
    if forecasts:
        total_pv = sum(p["pv_forecast_kwh"] for p in forecasts)
        total_load = sum(p["load_forecast_kwh"] for p in forecasts)
        print(f"Forecasts: {len(forecasts)} slots")
        print(f"  Total PV: {total_pv:.2f} kWh")
        print(f"  Total Load: {total_load:.2f} kWh")
    else:
        print("⚠️ Forecasts: MISSING")
    print("------------------------\n")
    
    # Run MPC Planner
    planner = HeliosPlanner(config_path=args.config)
    
    # Disable Kepler shadow in the planner config to avoid double running/logging
    planner.config["kepler"] = {"enabled": False}
    
    print("Running MPC Planner...")
    mpc_df = planner.generate_schedule(
        input_data=input_data,
        now_override=start_dt,
        save_to_file=False,
        record_training_episode=False
    )
    
    # Calculate MPC Cost
    # We need to use the same cost model as Kepler for fairness.
    # Kepler uses: import*price - export*price + (chg+dis)*wear
    # Let's compute it from the mpc_df
    
    k_config = config_to_kepler_config(planner.config)
    
    def calculate_cost(df, tag="MPC"):
        total_cost = 0.0
        wear_cost = k_config.wear_cost_sek_per_kwh
        
        # Ensure columns exist
        cols = ["adjusted_load_kwh", "adjusted_pv_kwh", "battery_charge_kw", "battery_discharge_kw", "import_price_sek_kwh", "export_price_sek_kwh"]
        for c in cols:
            if c not in df.columns:
                df[c] = 0.0
        
        # Water columns might be missing if no water heater
        water_cols = ["water_from_grid_kwh", "water_from_pv_kwh", "water_from_battery_kwh"]
        for c in water_cols:
            if c not in df.columns:
                df[c] = 0.0

        for _, row in df.iterrows():
            # Calculate Net Grid
            load = row["adjusted_load_kwh"]
            pv = row["adjusted_pv_kwh"]
            water = row["water_from_grid_kwh"] + row["water_from_pv_kwh"] + row["water_from_battery_kwh"]
            chg = row["battery_charge_kw"] * 0.25
            dis = row["battery_discharge_kw"] * 0.25
            
            net_grid_kwh = load + water + chg - pv - dis
            
            imp = max(0.0, net_grid_kwh)
            exp = max(0.0, -net_grid_kwh)
            
            imp_p = row["import_price_sek_kwh"]
            exp_p = row["export_price_sek_kwh"]
            
            slot_cost = (imp * imp_p) - (exp * exp_p) + (chg + dis) * wear_cost
            total_cost += slot_cost
            
        return total_cost

    mpc_cost = calculate_cost(mpc_df, "MPC")
    print(f"MPC Cost: {mpc_cost:.2f} SEK")
    
    # Run Kepler
    print("Running Kepler...")
    # We need to convert mpc_df (which has forecasts) to KeplerInput
    # Note: mpc_df has the *result* of MPC, but it also preserves the input forecasts.
    # So we can use it to drive Kepler.
    
    # Use initial SoC from input_data
    initial_soc = float(input_data["initial_state"].get("battery_kwh", 0.0))
    
    k_input = planner_to_kepler_input(mpc_df, initial_soc)
    solver = KeplerSolver()
    k_result = solver.solve(k_input, k_config)
    
    if k_result.is_optimal:
        print(f"Kepler Cost: {k_result.total_cost_sek:.2f} SEK")
        diff = mpc_cost - k_result.total_cost_sek
        print(f"Difference (MPC - Kepler): {diff:.2f} SEK")
        if diff > 0.01:
            print("✅ Kepler is cheaper!")
        elif diff < -0.01:
            print("⚠️ MPC is cheaper? (Should not happen if Kepler is optimal)")
        else:
            print("🤝 Parity.")
            
        # Print summary stats
        # Calculate MPC totals for display
        mpc_net = (mpc_df["adjusted_load_kwh"] 
                   + mpc_df.get("water_from_grid_kwh", 0) + mpc_df.get("water_from_pv_kwh", 0) + mpc_df.get("water_from_battery_kwh", 0)
                   + mpc_df["battery_charge_kw"]*0.25 
                   - mpc_df["adjusted_pv_kwh"] 
                   - mpc_df["battery_discharge_kw"]*0.25)
        mpc_imp = mpc_net.apply(lambda x: max(0, x)).sum()
        mpc_exp = mpc_net.apply(lambda x: max(0, -x)).sum()
        
        print(f"MPC Import: {mpc_imp:.2f} kWh")
        print(f"Kepler Import: {sum(s.grid_import_kwh for s in k_result.slots):.2f} kWh")
        print(f"MPC Export: {mpc_exp:.2f} kWh")
        print(f"Kepler Export: {sum(s.grid_export_kwh for s in k_result.slots):.2f} kWh")

        
    else:
        print(f"Kepler failed: {k_result.status_msg}")

if __name__ == "__main__":
    main()
