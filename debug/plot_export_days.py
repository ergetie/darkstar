import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import sys
import os


def plot_export_days(mpc_csv, kepler_csv, output_path):
    # Load Data
    try:
        mpc_df = pd.read_csv(mpc_csv)
        kepler_df = pd.read_csv(kepler_csv)
    except FileNotFoundError:
        print("CSV files not found.")
        return

    # Parse Dates
    time_col = mpc_df.columns[0]
    mpc_df[time_col] = pd.to_datetime(mpc_df[time_col], utc=True).dt.tz_convert("Europe/Stockholm")
    kepler_df[time_col] = pd.to_datetime(kepler_df[time_col], utc=True).dt.tz_convert(
        "Europe/Stockholm"
    )

    mpc_df["date_str"] = mpc_df[time_col].dt.date.astype(str)
    kepler_df["date_str"] = kepler_df[time_col].dt.date.astype(str)

    # Identify Top Export Days
    daily_export = kepler_df.groupby("date_str")["grid_export_kw"].sum()
    top_days = daily_export.sort_values(ascending=False).head(3).index.tolist()

    print(f"Plotting top export days: {top_days}")

    # Create Figure
    fig, axes = plt.subplots(len(top_days), 1, figsize=(15, 5 * len(top_days)), sharex=False)
    if len(top_days) == 1:
        axes = [axes]

    for i, day in enumerate(top_days):
        ax = axes[i]
        day_mpc = mpc_df[mpc_df["date_str"] == day]
        day_kepler = kepler_df[kepler_df["date_str"] == day]

        # Sort by time to ensure lines don't jump
        day_kepler = day_kepler.sort_values(time_col)
        day_mpc = day_mpc.sort_values(time_col)

        # Plot Price (Right Axis 1)
        ax2 = ax.twinx()
        if not day_mpc.empty and "import_price_sek_kwh" in day_mpc.columns:
            (p1,) = ax2.plot(
                day_mpc[time_col],
                day_mpc["import_price_sek_kwh"],
                color="black",
                linestyle=":",
                alpha=0.5,
                label="Price",
            )
        ax2.set_ylabel("Price (SEK/kWh)")
        ax2.yaxis.label.set_color("black")

        # Plot SoC (Right Axis 2)
        ax3 = ax.twinx()
        ax3.spines["right"].set_position(("axes", 1.15))

        # Use Red for SoC to contrast with Green/Purple/Orange
        (p2,) = ax3.plot(
            day_kepler[time_col],
            day_kepler["projected_soc_percent"],
            color="red",
            linewidth=2,
            label="SoC %",
        )
        ax3.set_ylabel("SoC (%)")
        ax3.yaxis.label.set_color("red")
        ax3.tick_params(axis="y", colors="red")
        ax3.set_ylim(0, 100)

        # Plot Export/Import (Left Axis) using STEP plots for clarity
        # fill_between with step='post' is supported in newer matplotlib, but let's be safe
        # We'll use step() and fill_between with step

        ax.fill_between(
            day_kepler[time_col],
            day_kepler["grid_export_kw"],
            0,
            step="post",
            color="purple",
            alpha=0.6,
            label="Export",
        )
        ax.fill_between(
            day_kepler[time_col],
            day_kepler["grid_import_kw"],
            0,
            step="post",
            color="orange",
            alpha=0.4,
            label="Import",
        )

        ax.set_title(f"Export Activity on {day}")
        ax.set_ylabel("Power (kW)")

        # Legend
        ax.legend(loc="upper left")

        # Format X
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Saved plot to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot export days")
    parser.add_argument("--mpc", type=str, default="benchmark_mpc_timeseries.csv")
    parser.add_argument("--kepler", type=str, default="benchmark_kepler_timeseries.csv")
    parser.add_argument("--output", type=str, default="benchmark_export_plot.png")
    args = parser.parse_args()

    plot_export_days(args.mpc, args.kepler, args.output)
