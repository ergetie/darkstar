import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import sys
import os

def plot_range(csv_path, output_path):
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    
    # Calculate Cumulative Savings
    df['cumulative_savings'] = df['savings'].cumsum()
    
    # Create Figure
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
    
    # Plot 1: Daily Cost Comparison
    width = 0.35
    ax1.bar(df['date'] - pd.Timedelta(days=0.2), df['mpc_cost'], width, label='MPC Cost', color='gray', alpha=0.7)
    ax1.bar(df['date'] + pd.Timedelta(days=0.2), df['kepler_cost'], width, label='Kepler Cost', color='#4CAF50', alpha=0.9)
    
    ax1.set_ylabel('Daily Cost (SEK)')
    ax1.set_title('Daily Cost Comparison: Kepler vs MPC')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Cumulative Savings
    ax2.plot(df['date'], df['cumulative_savings'], color='#2196F3', linewidth=2, marker='o', label='Cumulative Savings')
    ax2.fill_between(df['date'], df['cumulative_savings'], 0, color='#2196F3', alpha=0.1)
    
    ax2.set_ylabel('Cumulative Savings (SEK)')
    ax2.set_xlabel('Date')
    ax2.set_title(f"Total Savings: {df['savings'].sum():.2f} SEK over {len(df)} days")
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Format X Axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.xticks(rotation=45)
    
    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Saved plot to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot benchmark range results")
    parser.add_argument("--input", type=str, default="benchmark_results.csv", help="Input CSV file")
    parser.add_argument("--output", type=str, default="benchmark_range_plot.png", help="Output PNG file")
    args = parser.parse_args()
    
    plot_range(args.input, args.output)
