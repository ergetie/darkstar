import argparse
import pandas as pd
from datetime import datetime, timedelta, date
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from planner_legacy import HeliosPlanner
from ml.simulation.data_loader import SimulationDataLoader
from backend.kepler.solver import KeplerSolver
from backend.kepler.adapter import planner_to_kepler_input, config_to_kepler_config

def run_day_comparison(target_day: date, config_path: str):
    try:
        loader = SimulationDataLoader(config_path=config_path)
        start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))
        
        # Load inputs
        input_data = loader.get_window_inputs(start_dt)
        input_data["initial_state"] = loader.get_initial_state_from_history(start_dt)
        
        # Run MPC
        planner = HeliosPlanner(config_path=config_path)
        planner.config["kepler"] = {"enabled": False}
        
        mpc_df = planner.generate_schedule(
            input_data=input_data,
            now_override=start_dt,
            save_to_file=False,
            record_training_episode=False
        )
        
        # Calculate MPC Cost
        k_config = config_to_kepler_config(planner.config)
        wear_cost = k_config.wear_cost_sek_per_kwh
        
        # Ensure columns
        cols = ["adjusted_load_kwh", "adjusted_pv_kwh", "battery_charge_kw", "battery_discharge_kw", "import_price_sek_kwh", "export_price_sek_kwh"]
        for c in cols:
            if c not in mpc_df.columns:
                mpc_df[c] = 0.0
        
        water_cols = ["water_from_grid_kwh", "water_from_pv_kwh", "water_from_battery_kwh"]
        for c in water_cols:
            if c not in mpc_df.columns:
                mpc_df[c] = 0.0
                
        mpc_total_cost = 0.0
        for _, row in mpc_df.iterrows():
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
            mpc_total_cost += slot_cost
            
        # Run Kepler
        initial_soc = float(input_data["initial_state"].get("battery_kwh", 0.0))
        k_input = planner_to_kepler_input(mpc_df, initial_soc)
        solver = KeplerSolver()
        k_result = solver.solve(k_input, k_config)
        
        if k_result.is_optimal:
            return {
                "day": target_day,
                "mpc_cost": mpc_total_cost,
                "kepler_cost": k_result.total_cost_sek,
                "diff": mpc_total_cost - k_result.total_cost_sek,
                "status": "OK"
            }
        else:
            return {
                "day": target_day,
                "mpc_cost": mpc_total_cost,
                "kepler_cost": 0.0,
                "diff": 0.0,
                "status": f"Kepler Failed: {k_result.status_msg}"
            }
            
    except Exception as e:
        return {
            "day": target_day,
            "mpc_cost": 0.0,
            "kepler_cost": 0.0,
            "diff": 0.0,
            "status": f"Error: {str(e)}"
        }

def main():
    parser = argparse.ArgumentParser(description="Benchmark Kepler vs MPC over a date range")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back (if start/end not provided)")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    
    if args.start and args.end:
        start_date = datetime.fromisoformat(args.start).date()
        end_date = datetime.fromisoformat(args.end).date()
    else:
        end_date = datetime.now().date() - timedelta(days=1) # Yesterday
        start_date = end_date - timedelta(days=args.days - 1)
        
    print(f"Benchmarking from {start_date} to {end_date}...")
    
    results = []
    current = start_date
    while current <= end_date:
        print(f"Processing {current}...", end="", flush=True)
        res = run_day_comparison(current, args.config)
        results.append(res)
        print(f" {res['status']} (Diff: {res['diff']:.2f} SEK)")
        current += timedelta(days=1)
        
    # Summary
    df = pd.DataFrame(results)
    if df.empty:
        print("No results.")
        return

    print("\n--- Benchmark Results ---")
    print(df[["day", "mpc_cost", "kepler_cost", "diff", "status"]].to_string(index=False))
    
    valid = df[df["status"] == "OK"]
    if not valid.empty:
        total_mpc = valid["mpc_cost"].sum()
        total_kepler = valid["kepler_cost"].sum()
        total_diff = valid["diff"].sum()
        days = len(valid)
        
        print("\n--- Aggregate Stats (OK days only) ---")
        print(f"Days: {days}")
        print(f"Total MPC Cost:    {total_mpc:.2f} SEK")
        print(f"Total Kepler Cost: {total_kepler:.2f} SEK")
        print(f"Total Savings:     {total_diff:.2f} SEK")
        print(f"Avg Daily Savings: {total_diff / days:.2f} SEK")
        print(f"Improvement:       {(total_diff / total_mpc * 100):.1f}%")
    else:
        print("\nNo valid days to aggregate.")

if __name__ == "__main__":
    main()
