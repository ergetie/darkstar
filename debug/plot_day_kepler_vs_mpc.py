import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from planner_legacy import HeliosPlanner
from ml.simulation.data_loader import SimulationDataLoader
from backend.kepler.solver import KeplerSolver
from backend.kepler.adapter import planner_to_kepler_input, config_to_kepler_config, kepler_result_to_dataframe

def main():
    parser = argparse.ArgumentParser(description="Plot Kepler vs MPC for a specific day")
    parser.add_argument("--day", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--output", type=str, default=None, help="Output filename (optional)")
    args = parser.parse_args()

    target_day = datetime.fromisoformat(args.day).date()
    print(f"Generating plot for {target_day}...")

    # Load Data & Run MPC
    loader = SimulationDataLoader(config_path=args.config)
    start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))
    # input_data = loader.build_planner_input(start_dt)
    input_data = loader.get_window_inputs(start_dt)
    input_data["initial_state"] = loader.get_initial_state_from_history(start_dt)
    
    planner = HeliosPlanner(config_path=args.config)
    planner.config["kepler"] = {"enabled": False}
    
    mpc_df = planner.generate_schedule(
        input_data=input_data,
        now_override=start_dt,
        save_to_file=False,
        record_training_episode=False
    )
    
    # Run Kepler
    initial_soc = float(input_data["initial_state"].get("battery_kwh", 0.0))
    k_input = planner_to_kepler_input(mpc_df, initial_soc)
    k_config = config_to_kepler_config(planner.config)
    solver = KeplerSolver()
    k_result = solver.solve(k_input, k_config)
    
    if not k_result.is_optimal:
        print(f"Kepler failed: {k_result.status_msg}")
        return

    k_df = kepler_result_to_dataframe(k_result)
    
    # Prepare Plot Data
    # Align indices
    mpc_df.index = pd.to_datetime(mpc_df.index)
    k_df.index = pd.to_datetime(k_df.index)
    
    # Plotting
    fig, axes = plt.subplots(4, 1, figsize=(12, 16), sharex=True)
    
    # 1. Prices
    ax = axes[0]
    ax.plot(mpc_df.index, mpc_df["import_price_sek_kwh"], label="Import Price", color="red", linestyle="--")
    ax.plot(mpc_df.index, mpc_df["export_price_sek_kwh"], label="Export Price", color="green", linestyle=":")
    ax.set_ylabel("Price (SEK/kWh)")
    ax.set_title(f"Prices - {target_day}")
    ax.legend()
    ax.grid(True)
    
    # 2. SoC
    ax = axes[1]
    # MPC SoC is usually 'battery_soc_kwh' or derived from percent
    if "projected_soc_kwh" in mpc_df.columns:
        ax.plot(mpc_df.index, mpc_df["projected_soc_kwh"], label="MPC SoC", color="blue")
    elif "battery_soc_kwh" in mpc_df.columns:
        ax.plot(mpc_df.index, mpc_df["battery_soc_kwh"], label="MPC SoC", color="blue")
    else:
        # Fallback to percent * capacity
        cap = k_config.capacity_kwh
        soc_pct = mpc_df.get("projected_soc_percent", mpc_df.get("battery_soc_percent", 0.0))
        ax.plot(mpc_df.index, soc_pct / 100.0 * cap, label="MPC SoC (est)", color="blue")
        
    ax.plot(k_df.index, k_df["kepler_soc_kwh"], label="Kepler SoC", color="orange", linestyle="--")
    ax.set_ylabel("SoC (kWh)")
    ax.set_title("State of Charge")
    ax.legend()
    ax.grid(True)
    
    # 3. Battery Power
    ax = axes[2]
    # MPC
    mpc_net_bat = mpc_df["battery_charge_kw"] - mpc_df["battery_discharge_kw"]
    ax.plot(mpc_df.index, mpc_net_bat, label="MPC Net Battery (kW)", color="blue", alpha=0.7)
    
    # Kepler (convert kWh to kW)
    # Assuming 15 min slots
    k_net_bat = (k_df["kepler_charge_kwh"] - k_df["kepler_discharge_kwh"]) * 4.0
    ax.plot(k_df.index, k_net_bat, label="Kepler Net Battery (kW)", color="orange", linestyle="--", alpha=0.7)
    
    ax.set_ylabel("Battery Power (kW) (+Chg/-Dis)")
    ax.set_title("Battery Activity")
    ax.legend()
    ax.grid(True)
    
    # 4. Grid Power
    ax = axes[3]
    # MPC
    # Calculate Net Grid (kW)
    # net_grid_kw = (load + water + charge - pv - discharge) / 0.25 (if energy) or just sum of kW
    # Load/PV are kWh per 15 min. Charge/Discharge are kW.
    # So Net Grid (kW) = (Load_kWh + Water_kWh - PV_kWh) * 4 + Charge_kW - Discharge_kW
    
    mpc_load_kw = mpc_df["adjusted_load_kwh"] * 4.0
    mpc_pv_kw = mpc_df["adjusted_pv_kwh"] * 4.0
    mpc_water_kw = (mpc_df.get("water_from_grid_kwh", 0) + mpc_df.get("water_from_pv_kwh", 0) + mpc_df.get("water_from_battery_kwh", 0)) * 4.0
    mpc_chg_kw = mpc_df["battery_charge_kw"]
    mpc_dis_kw = mpc_df["battery_discharge_kw"]
    
    mpc_net_grid_kw = mpc_load_kw + mpc_water_kw + mpc_chg_kw - mpc_pv_kw - mpc_dis_kw
    
    ax.plot(mpc_df.index, mpc_net_grid_kw, label="MPC Net Grid (kW)", color="purple", alpha=0.7)
    
    # Kepler
    k_net_grid = (k_df["kepler_import_kwh"] - k_df["kepler_export_kwh"]) * 4.0
    ax.plot(k_df.index, k_net_grid, label="Kepler Net Grid (kW)", color="green", linestyle="--", alpha=0.7)
    
    ax.set_ylabel("Grid Power (kW) (+Imp/-Exp)")
    ax.set_title("Grid Activity")
    ax.legend()
    ax.grid(True)
    
    # Format x-axis
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    
    plt.tight_layout()
    
    if args.output:
        plt.savefig(args.output)
        print(f"Saved plot to {args.output}")
    else:
        plt.show()

if __name__ == "__main__":
    main()
