import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import sys
import os

def plot_timeseries(mpc_csv, kepler_csv, output_path):
    # Load Data
    try:
        mpc_df = pd.read_csv(mpc_csv)
        kepler_df = pd.read_csv(kepler_csv)
    except FileNotFoundError:
        print("CSV files not found. Run benchmark_range.py first.")
        return

    # Parse Dates
    # Note: 'start_time' or index might be the timestamp column depending on how it was saved.
    # benchmark_range.py saves the index as a column if index=True? No, index=False?
    # Wait, mpc_df comes from planner which has DatetimeIndex. 
    # pd.concat preserves index. to_csv saves index if index=True (default).
    # I didn't specify index=False for timeseries in benchmark_range.py.
    # So the first column is likely the timestamp.
    
    # Let's assume the first column is 'start_time' or unnamed index
    time_col = mpc_df.columns[0]
    mpc_df[time_col] = pd.to_datetime(mpc_df[time_col], utc=True).dt.tz_convert('Europe/Stockholm')
    kepler_df[time_col] = pd.to_datetime(kepler_df[time_col], utc=True).dt.tz_convert('Europe/Stockholm')
    
    mpc_df = mpc_df.sort_values(time_col)
    kepler_df = kepler_df.sort_values(time_col)
    
    # Create Figure
    fig, axes = plt.subplots(5, 1, figsize=(15, 20), sharex=True)
    
    # Plot 1: Prices
    ax = axes[0]
    ax.plot(mpc_df[time_col], mpc_df['import_price_sek_kwh'], label='Import Price', color='black', linewidth=1)
    ax.set_ylabel('Price (SEK/kWh)')
    ax.set_title('Electricity Prices')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)
    
    # Plot 2: SoC
    ax = axes[1]
    ax.plot(mpc_df[time_col], mpc_df['projected_soc_percent'], label='MPC SoC %', color='gray', linestyle='--')
    ax.plot(kepler_df[time_col], kepler_df['projected_soc_percent'], label='Kepler SoC %', color='#4CAF50', linewidth=2)
    ax.set_ylabel('SoC (%)')
    ax.set_title('State of Charge')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)
    
    # Plot 3: Battery Power (Charge/Discharge)
    ax = axes[2]
    # MPC
    ax.fill_between(mpc_df[time_col], mpc_df['battery_charge_kw'], 0, color='red', alpha=0.3, label='MPC Charge')
    ax.fill_between(mpc_df[time_col], -mpc_df['battery_discharge_kw'], 0, color='green', alpha=0.3, label='MPC Discharge')
    # Kepler (Line)
    # Calculate net power for Kepler
    kepler_net_power = kepler_df['battery_charge_kw'] - kepler_df['battery_discharge_kw']
    ax.plot(kepler_df[time_col], kepler_net_power, color='blue', linewidth=1, label='Kepler Net Power')
    
    ax.set_ylabel('Power (kW)')
    ax.set_title('Battery Power (+ Charge / - Discharge)')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    # Plot 4: Grid Import/Export
    ax = axes[3]
    # Calculate MPC Net Grid if not present
    # mpc_df might not have 'import_kwh' if it wasn't in the original DF (as discovered).
    # But we can calculate it or use what we have.
    # benchmark_range.py saves the raw DF.
    # Let's try to use 'import_kwh' if available, else calculate.
    
    # Kepler has grid_import_kw
    ax.plot(kepler_df[time_col], kepler_df['grid_import_kw'], label='Kepler Import kW', color='orange')
    ax.plot(kepler_df[time_col], -kepler_df['grid_export_kw'], label='Kepler Export kW', color='purple')
    
    ax.set_ylabel('Grid Power (kW)')
    ax.set_title('Grid Interaction')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)
    
    # Plot 5: Water Heating
    ax = axes[4]
    # Kepler doesn't support water heating yet (always 0)
    # MPC does.
    if 'water_from_grid_kwh' in mpc_df.columns:
        mpc_water = (mpc_df['water_from_grid_kwh'] + mpc_df.get('water_from_pv_kwh', 0) + mpc_df.get('water_from_battery_kwh', 0)) * 4 # kWh -> kW
        ax.plot(mpc_df[time_col], mpc_water, label='MPC Water Heating (kW)', color='blue')
    
    ax.set_ylabel('Water Heating (kW)')
    ax.set_title('Water Heating')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)
    
    # Format X Axis
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot benchmark timeseries")
    parser.add_argument("--mpc", type=str, default="benchmark_mpc_timeseries.csv", help="MPC CSV file")
    parser.add_argument("--kepler", type=str, default="benchmark_kepler_timeseries.csv", help="Kepler CSV file")
    parser.add_argument("--output", type=str, default="benchmark_timeseries_plot.png", help="Output PNG file")
    args = parser.parse_args()
    
    plot_timeseries(args.mpc, args.kepler, args.output)
