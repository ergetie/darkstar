import argparse
import pandas as pd
import pytz
import traceback
from datetime import datetime, timedelta
import sys
import os
import json
import sqlite3

# Add project root to path
sys.path.append(os.getcwd())

from planner import HeliosPlanner
from ml.simulation.data_loader import SimulationDataLoader
from backend.kepler.solver import KeplerSolver
from backend.kepler.adapter import planner_to_kepler_input, config_to_kepler_config, kepler_result_to_dataframe

def run_day(date_str, config_path="config.yaml"):
    target_day = datetime.fromisoformat(date_str).date()
    
    # Load Data & Run MPC
    loader = SimulationDataLoader(config_path=config_path)
    start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))
    
    try:
        input_data = loader.get_window_inputs(start_dt)
        input_data["initial_state"] = loader.get_initial_state_from_history(start_dt)
        
        # Check for critical data
        prices = input_data.get("price_data", [])
        forecasts = input_data.get("forecast_data", [])
        
        if not prices:
            print(f" [Missing Prices]", end="")
            return None
            
        total_load = sum(f.get("load_forecast_kwh", 0) for f in forecasts)
        total_pv = sum(f.get("pv_forecast_kwh", 0) for f in forecasts)
        
        initial_soc = float(input_data["initial_state"].get("battery_kwh", 0.0))
        
        if total_load < 1.0:
             print(f" [Low Load: {total_load:.2f} kWh]", end="")
        else:
             print(f" [SoC:{initial_soc:.1f} L:{total_load:.1f} P:{total_pv:.1f}]", end="")
             
        planner = HeliosPlanner(config_path=config_path)
        # planner.config["kepler"] = {"enabled": False} # Force MPC - BAD, wipes config
        if "kepler" in planner.config:
            planner.config["kepler"]["primary_planner"] = False
        
        mpc_df = planner.generate_schedule(
            input_data=input_data,
            now_override=start_dt,
            save_to_file=False,
            record_training_episode=False
        )
        
        df_load = mpc_df["load_forecast_kwh"].sum() if "load_forecast_kwh" in mpc_df else 0
        df_dis = mpc_df["battery_discharge_kw"].sum() * 0.25 if "battery_discharge_kw" in mpc_df else 0
        df_char = mpc_df["battery_charge_kw"].sum() * 0.25 if "battery_charge_kw" in mpc_df else 0
        df_pv = mpc_df["pv_forecast_kwh"].sum() if "pv_forecast_kwh" in mpc_df else 0
        df_imp = mpc_df["import_kwh"].sum() if "import_kwh" in mpc_df else 0
        
        print(f" [Bal: L{df_load:.1f} P{df_pv:.1f} D{df_dis:.1f} C{df_char:.1f} I{df_imp:.1f}]", end="")
        print(f" [Rows: {len(mpc_df)}]")
        if len(mpc_df) > 0:
            print(mpc_df[["load_forecast_kwh", "pv_forecast_kwh", "battery_discharge_kw"]].head(3))
        
        # Calculate MPC Cost manually (same logic as compare_kepler_vs_mpc.py)
        mpc_cost = 0.0
        mpc_import = 0.0
        mpc_export = 0.0
        
        # Ensure columns exist
        cols = ["adjusted_load_kwh", "adjusted_pv_kwh", "battery_charge_kw", "battery_discharge_kw", "import_price_sek_kwh", "export_price_sek_kwh"]
        for c in cols:
            if c not in mpc_df.columns:
                mpc_df[c] = 0.0
        
        # Water columns
        water_cols = ["water_from_grid_kwh", "water_from_pv_kwh", "water_from_battery_kwh"]
        for c in water_cols:
            if c not in mpc_df.columns:
                mpc_df[c] = 0.0

        k_config = config_to_kepler_config(planner.config)
        wear_cost = k_config.wear_cost_sek_per_kwh

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
            
            mpc_cost += slot_cost
            mpc_import += imp
            mpc_export += exp

        # Run Kepler
        initial_soc = float(input_data["initial_state"].get("battery_kwh", 0.0))
        k_input = planner_to_kepler_input(mpc_df, initial_soc)
        k_config = config_to_kepler_config(planner.config)
        solver = KeplerSolver()
        k_result = solver.solve(k_input, k_config)
        
        if not k_result.is_optimal:
            return None
            
        k_cost = k_result.total_cost_sek
        
        # Calculate Financial Cost (Import - Export) for Kepler using ACTUALS
        k_financial_cost = 0.0
        k_import = 0.0
        k_export = 0.0
        
        # Convert Kepler result to DataFrame for timeseries
        # Get capacity from config
        battery_cap = float(planner.config.get("system", {}).get("battery", {}).get("capacity_kwh", 
                            planner.config.get("battery", {}).get("capacity_kwh", 10.0)))
                            
        kepler_df = kepler_result_to_dataframe(k_result, capacity_kwh=battery_cap, initial_soc_kwh=initial_soc)
        
        # Merge forecast and price columns from mpc_df into kepler_df
        # Ensure indices match
        if not mpc_df.empty and not kepler_df.empty:
             # We assume they cover the same range. 
             # Use join to be safe
             cols_to_add = ["load_forecast_kwh", "pv_forecast_kwh", "import_price_sek_kwh", "export_price_sek_kwh"]
             # Only add if not present
             cols_to_add = [c for c in cols_to_add if c not in kepler_df.columns]
             kepler_df = kepler_df.join(mpc_df[cols_to_add], how="left")
        
        # Fetch Actuals for Cost Calculation (Backtest against Reality)
        # We need to query the DB for the actual load/pv for this day
        actuals_df = pd.DataFrame()
        try:
            with sqlite3.connect(loader.db_path) as conn:
                # Get start/end of the mpc_df window
                if not mpc_df.empty:
                    s_start = mpc_df.index.min().isoformat()
                    s_end = mpc_df.index.max().isoformat()
                    query = """
                        SELECT slot_start, load_kwh, pv_kwh 
                        FROM slot_observations 
                        WHERE slot_start >= ? AND slot_start <= ?
                    """
                    actuals_df = pd.read_sql_query(query, conn, params=(s_start, s_end))
                    if not actuals_df.empty:
                        actuals_df["slot_start"] = pd.to_datetime(actuals_df["slot_start"], utc=True).dt.tz_convert(loader.timezone)
                        actuals_df = actuals_df.set_index("slot_start")
        except Exception as e:
            print(f" [Warning: Could not fetch actuals: {e}]", end="")

        # Now calculate Kepler Financial Cost using ACTUALS
        for t, row in kepler_df.iterrows():
             # Default to forecast
            load = row["load_forecast_kwh"] 
            pv = row["pv_forecast_kwh"]
            
            # Try to get actuals
            if not actuals_df.empty and t in actuals_df.index:
                a_row = actuals_df.loc[t]
                if pd.notna(a_row["load_kwh"]):
                    load = float(a_row["load_kwh"])
                if pd.notna(a_row["pv_kwh"]):
                    pv = float(a_row["pv_kwh"])
            
            chg = row["battery_charge_kw"] * 0.25
            dis = row["battery_discharge_kw"] * 0.25
            
            # Net Grid = House Load + Battery Charge - PV - Battery Discharge
            net = load + chg - pv - dis
            
            imp = max(0.0, net)
            exp = max(0.0, -net)
            
            k_financial_cost += (imp * row["import_price_sek_kwh"]) - (exp * row["export_price_sek_kwh"])
            k_import += imp
            k_export += exp
            

        
        # Calculate MPC Financial Cost
        mpc_financial_cost = 0.0
        for _, row in mpc_df.iterrows():
            imp = max(0.0, row["adjusted_load_kwh"] + row["battery_charge_kw"]*0.25 - row["adjusted_pv_kwh"] - row["battery_discharge_kw"]*0.25) # Approx
            # Better: use the calculated imp/exp from the loop above
            pass



        # Re-calculate MPC financial cost properly using ACTUALS if available
        mpc_financial_cost = 0.0
        
        # We iterate through mpc_df (the plan) and try to match with actuals
        for t, row in mpc_df.iterrows():
            # Default to forecast if actuals missing
            load = row["load_forecast_kwh"] # Use raw forecast, not adjusted
            pv = row["pv_forecast_kwh"]
            
            # Try to get actuals
            if not actuals_df.empty and t in actuals_df.index:
                a_row = actuals_df.loc[t]
                # Use actuals if valid (not None/NaN)
                if pd.notna(a_row["load_kwh"]):
                    load = float(a_row["load_kwh"])
                if pd.notna(a_row["pv_kwh"]):
                    pv = float(a_row["pv_kwh"])
            
            # Note: Actual Load (sensor.inverter_total_load_consumption) typically INCLUDES water heating
            # if the water heater is monitored. Since the user ran the MPC, the actual load
            # reflects the MPC's water scheduling. So we do NOT add row["water..."] here.
            # We ONLY add battery charge/discharge from the plan.
            
            chg = row["battery_charge_kw"] * 0.25
            dis = row["battery_discharge_kw"] * 0.25
            
            # Net Grid = House Load + Battery Charge - PV - Battery Discharge
            net = load + chg - pv - dis
            
            imp = max(0.0, net)
            exp = max(0.0, -net)
            mpc_financial_cost += (imp * row["import_price_sek_kwh"]) - (exp * row["export_price_sek_kwh"])

        return {
            "date": date_str,
            "mpc_cost": mpc_financial_cost, # Report Financial Cost to User
            "kepler_cost": k_financial_cost, # Report Financial Cost to User
            "mpc_objective_cost": mpc_cost, # Keep internal objective cost for debug
            "kepler_objective_cost": k_cost, # Keep internal objective cost for debug
            "mpc_import": mpc_import,
            "kepler_import": k_import,
            "mpc_export": mpc_export,
            "kepler_export": k_export,
            "savings": mpc_financial_cost - k_financial_cost,
            "mpc_df": mpc_df,
            "kepler_df": kepler_df
        }
        
    except Exception as e:
        traceback.print_exc()
        print(f"Error processing {date_str}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Benchmark Kepler vs MPC over range")
    parser.add_argument("--days", type=int, default=30, help="Number of days back")
    parser.add_argument("--output", type=str, default="benchmark_results.csv", help="Output CSV file")
    args = parser.parse_args()
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=args.days)
    
    results = []
    all_mpc_dfs = []
    all_kepler_dfs = []
    
    current_date = start_date
    
    print(f"Running benchmark from {start_date} to {end_date}...")
    
    while current_date <= end_date:
        date_str = current_date.isoformat()
        print(f"Processing {date_str}...", end="", flush=True)
        
        res = run_day(date_str)
        if res:
            results.append({k: v for k, v in res.items() if k not in ["mpc_df", "kepler_df"]})
            
            # Process MPC DF
            m_df = res["mpc_df"].copy()
            m_df["date"] = date_str
            m_df["planner"] = "MPC"
            # Filter for the specific day to avoid overlaps
            # Ensure start_time is datetime
            if not m_df.empty:
                if not pd.api.types.is_datetime64_any_dtype(m_df.index):
                    m_df.index = pd.to_datetime(m_df.index, utc=True)
                # Filter: start_time date == current_date
                # Note: m_df index is start_time. 
                # We need to handle timezone. current_date is local date.
                # Let's assume index is tz-aware.
                # We want rows where the local date matches current_date.
                # But simpler: just take the first 24 hours if it starts at 00:00?
                # Or filter by date string.
                # Let's use the date column we just added? No, that's the run date.
                
                # Robust filter:
                # Convert index to local tz (Europe/Stockholm) and check date.
                tz = pytz.timezone("Europe/Stockholm")
                m_df_local = m_df.index.tz_convert(tz)
                mask = m_df_local.date == current_date
                m_df = m_df[mask]
            
            all_mpc_dfs.append(m_df)
            
            # Process Kepler DF
            k_df = res["kepler_df"].copy()
            k_df["date"] = date_str
            k_df["planner"] = "Kepler"
            
            if not k_df.empty:
                if not pd.api.types.is_datetime64_any_dtype(k_df.index):
                    k_df.index = pd.to_datetime(k_df.index, utc=True)
                
                k_df_local = k_df.index.tz_convert(tz)
                mask = k_df_local.date == current_date
                k_df = k_df[mask]
                
            all_kepler_dfs.append(k_df)
            
            print(f" Done. MPC: {res['mpc_cost']:.2f} SEK, Kepler: {res['kepler_cost']:.2f} SEK. Savings: {res['savings']:.2f} SEK")
        else:
            print(" Skipped (No Data/Error)")
            
        current_date += timedelta(days=1)
        
    if results:
        # Save Summary
        df = pd.DataFrame(results)
        df.to_csv(args.output, index=False)
        print(f"\nSaved summary to {args.output}")
        
        # Save Timeseries
        if all_mpc_dfs:
            full_mpc = pd.concat(all_mpc_dfs)
            full_mpc.to_csv("benchmark_mpc_timeseries.csv")
            print("Saved MPC timeseries to benchmark_mpc_timeseries.csv")
            
        if all_kepler_dfs:
            full_kepler = pd.concat(all_kepler_dfs)
            full_kepler.to_csv("benchmark_kepler_timeseries.csv")
            print("Saved Kepler timeseries to benchmark_kepler_timeseries.csv")
        
        print("\nSummary:")
        print(f"Total Days: {len(df)}")
        print(f"Total MPC Cost: {df['mpc_cost'].sum():.2f} SEK")
        print(f"Total Kepler Cost: {df['kepler_cost'].sum():.2f} SEK")
        print(f"Total Savings: {df['savings'].sum():.2f} SEK")
        print(f"Avg Daily Savings: {df['savings'].mean():.2f} SEK")

if __name__ == "__main__":
    main()
