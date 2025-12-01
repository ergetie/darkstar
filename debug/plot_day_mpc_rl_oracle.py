from __future__ import annotations

"""
Plot MPC vs RL vs Oracle actions for a single day.

Usage:
    PYTHONPATH=. python debug/plot_day_mpc_rl_oracle.py --day 2025-11-20

This generates a single PNG with three stacked panels (MPC, RL, Oracle)
showing price, battery power, SoC, and export for 24h, and attempts to
open it with the default image viewer.
"""

import argparse
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.policy.antares_rl_policy import AntaresRLPolicyV1
from ml.simulation.env import AntaresMPCEnv


def _load_latest_rl_run(engine: LearningEngine) -> Dict[str, str]:
    # Only consider PPO-style RL runs that have a Stable Baselines model.zip.
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        row = conn.execute(
            """
            SELECT run_id, artifact_dir
            FROM antares_rl_runs
            WHERE algo LIKE 'ppo%'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise SystemExit(
            "[plot-day] No PPO RL runs found in antares_rl_runs; "
            "train RL v1/v1.1 first."
        )
    return {"run_id": row[0], "artifact_dir": row[1]}


def _build_mpc_schedule(day: str) -> pd.DataFrame:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()

    schedule["start_time"] = pd.to_datetime(schedule["start_time"])
    schedule = schedule.sort_values("start_time")
    schedule["battery_charge_kw"] = schedule.get(
        "battery_charge_kw", schedule.get("charge_kw", 0.0)
    ).astype(float)
    schedule["battery_discharge_kw"] = schedule.get("battery_discharge_kw", 0.0).astype(float)
    # Convention: positive net_battery_kw = charging the battery, negative = discharging.
    schedule["net_battery_kw"] = schedule["battery_charge_kw"] - schedule["battery_discharge_kw"]
    schedule["soc_percent"] = schedule.get("projected_soc_percent", 0.0).astype(float)
    # Load/PV (kWh -> kW) for price panel context.
    if "adjusted_load_kwh" in schedule.columns:
        load_kwh = schedule["adjusted_load_kwh"].astype(float)
    else:
        load_kwh = schedule.get("load_forecast_kwh", 0.0).astype(float)
    if "adjusted_pv_kwh" in schedule.columns:
        pv_kwh = schedule["adjusted_pv_kwh"].astype(float)
    else:
        pv_kwh = schedule.get("pv_forecast_kwh", 0.0).astype(float)
    schedule["load_kw"] = load_kwh * 4.0
    schedule["pv_kw"] = pv_kwh * 4.0
    schedule["import_price"] = schedule.get("import_price_sek_kwh", 0.0).astype(float)
    schedule["export_kwh"] = schedule.get("export_kwh", 0.0).astype(float)
    schedule["export_kw"] = schedule["export_kwh"] * 4.0
    return schedule


def _build_rl_schedule(day: str, policy: AntaresRLPolicyV1) -> pd.DataFrame:
    env = AntaresMPCEnv(config_path="config.yaml")
    state = env.reset(day)
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()

    rows: List[Dict[str, Any]] = []
    slot_index = 0
    while True:
        row = schedule.iloc[slot_index].copy()
        start_time = pd.to_datetime(row["start_time"])
        import_price = float(row.get("import_price_sek_kwh", 0.0) or 0.0)
        export_price = float(row.get("export_price_sek_kwh", import_price) or import_price)
        export_kwh = float(row.get("export_kwh", 0.0) or 0.0)

        # State fed to the policy; index 3 is projected SoC percent in the
        # current contract.
        action = policy.predict(state)

        # Step the environment so we get the *effective* actions and SoC that
        # were actually used after clamping and safety checks.
        result = env.step(action=action)

        eff_charge = float(result.info.get("battery_charge_kw", 0.0))
        eff_discharge = float(result.info.get("battery_discharge_kw", 0.0))
        eff_net = float(result.info.get("net_battery_kw", eff_charge - eff_discharge))
        soc_percent_internal = float(result.info.get("soc_percent_internal", 0.0))

        rows.append(
            {
                "start_time": start_time,
                "import_price": import_price,
                "export_price": export_price,
                "rl_charge_kw_eff": eff_charge,
                "rl_discharge_kw_eff": eff_discharge,
                # Convention: positive = charging, negative = discharging.
                "rl_net_battery_kw": eff_net,
                "rl_soc_percent": soc_percent_internal,
                "export_kwh": export_kwh,
                "export_kw": export_kwh * 4.0,
            }
        )

        state = result.next_state
        slot_index += 1
        if result.done or slot_index >= len(schedule):
            break

    df = pd.DataFrame(rows)
    df = df.sort_values("start_time")
    return df


def _build_oracle_schedule(day: str) -> pd.DataFrame:
    df = solve_optimal_schedule(day)
    df = df.copy()
    df["start_time"] = pd.to_datetime(df["slot_start"])
    df = df.sort_values("start_time")

    # Convert kWh decisions to kW for plotting (assuming 15 min slots)
    slot_hours = df.get("slot_hours", 0.25).astype(float).replace(0.0, 0.25)
    df["oracle_charge_kw"] = df["oracle_charge_kwh"].astype(float) / slot_hours
    df["oracle_discharge_kw"] = df["oracle_discharge_kwh"].astype(float) / slot_hours
    # Convention: positive net_battery_kw = charging, negative = discharging.
    df["oracle_net_battery_kw"] = df["oracle_charge_kw"] - df["oracle_discharge_kw"]
    df["oracle_soc_percent"] = df.get("oracle_soc_percent", 0.0).astype(float)
    df["import_price"] = df.get("import_price_sek_kwh", 0.0).astype(float)
    df["export_price"] = df.get("export_price_sek_kwh", df["import_price"]).astype(float)
    df["export_kw"] = df["oracle_grid_export_kwh"].astype(float) / slot_hours
    return df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot MPC vs RL vs Oracle battery actions for a single day.",
    )
    parser.add_argument("--day", required=True, help="Day to plot (YYYY-MM-DD)")
    args = parser.parse_args()

    day = args.day
    engine = get_learning_engine()
    rl_run = _load_latest_rl_run(engine)
    policy = AntaresRLPolicyV1.load_from_dir(rl_run["artifact_dir"])

    print(f"[plot-day] Building MPC schedule for {day}...")
    mpc_df = _build_mpc_schedule(day)
    print(f"[plot-day] Building RL schedule for {day} (run {rl_run['run_id'][:8]})...")
    rl_df = _build_rl_schedule(day, policy)
    print(f"[plot-day] Solving Oracle schedule for {day}...")
    oracle_df = _build_oracle_schedule(day)

    # Restrict all schedules to the calendar day window [day 00:00, day+1 00:00)
    day_ts = pd.Timestamp(day)
    tz = mpc_df["start_time"].dt.tz if mpc_df["start_time"].dt.tz is not None else None
    if tz is not None:
        day_start = day_ts.tz_localize(tz)
    else:
        day_start = day_ts
    day_end = day_start + pd.Timedelta(days=1)

    mpc_df = mpc_df[(mpc_df["start_time"] >= day_start) & (mpc_df["start_time"] < day_end)].copy()
    rl_df = rl_df[(rl_df["start_time"] >= day_start) & (rl_df["start_time"] < day_end)].copy()
    oracle_df = oracle_df[
        (oracle_df["start_time"] >= day_start) & (oracle_df["start_time"] < day_end)
    ].copy()

    # Align x-axis across all (same 24h window)
    xmin = day_start
    xmax = day_end

    # Common y-limits
    all_price = pd.concat(
        [mpc_df["import_price"], rl_df["import_price"], oracle_df["import_price"]]
    )
    price_min, price_max = float(all_price.min()), float(all_price.max())

    all_net_batt = pd.concat(
        [
            mpc_df["net_battery_kw"],
            rl_df["rl_net_battery_kw"],
            oracle_df["oracle_net_battery_kw"],
        ]
    )
    pb_min, pb_max = float(all_net_batt.min()), float(all_net_batt.max())

    all_soc = pd.concat(
        [
            mpc_df["soc_percent"],
            rl_df["rl_soc_percent"],
            oracle_df["oracle_soc_percent"],
        ]
    )
    soc_min, soc_max = float(all_soc.min()), float(all_soc.max())

    all_export = pd.concat(
        [
            mpc_df["export_kw"],
            rl_df["export_kw"],
            oracle_df["export_kw"],
        ]
    )
    exp_min, exp_max = float(all_export.min()), float(all_export.max())

    fig, axes = plt.subplots(4, 1, figsize=(16, 14), sharex=True)
    fig.suptitle(f"Antares: MPC vs RL vs Oracle — {day}", fontsize=14)

    # Panel 0: Price only (common)
    ax_price = axes[0]
    ax_price.set_title("Price, load, PV (common)")
    ax_price.plot(mpc_df["start_time"], mpc_df["import_price"], color="tab:blue", label="Price")
    ax_price.set_ylabel("SEK/kWh")
    ax_price.set_ylim(price_min * 0.9, price_max * 1.1)
    # Secondary axis: load and PV power (kW) for context.
    ax_price2 = ax_price.twinx()
    if "load_kw" in mpc_df.columns:
        ax_price2.plot(
            mpc_df["start_time"],
            mpc_df["load_kw"],
            color="tab:gray",
            alpha=0.7,
            label="Load kW",
        )
    if "pv_kw" in mpc_df.columns:
        ax_price2.plot(
            mpc_df["start_time"],
            mpc_df["pv_kw"],
            color="tab:olive",
            alpha=0.7,
            label="PV kW",
        )
    ax_price2.set_ylabel("kW")

    max_abs_kw = max(abs(pb_min), abs(pb_max), 1.0)

    # Panel 1: MPC
    ax = axes[1]
    ax.set_title("MPC")
    ax1 = ax
    ax2 = ax1.twinx()
    ax1.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(mpc_df["start_time"], mpc_df["net_battery_kw"], label="Net Batt kW", color="tab:green")
    ax1.plot(mpc_df["start_time"], mpc_df["export_kw"], label="Export kW", color="tab:red")
    ax2.plot(mpc_df["start_time"], mpc_df["soc_percent"], label="SoC %", color="tab:orange")
    ax1.set_ylabel("kW")
    ax2.set_ylabel("SoC %")
    ax1.set_ylim(-max_abs_kw * 1.1, max_abs_kw * 1.1)
    ax2.set_ylim(soc_min * 0.9, soc_max * 1.1)

    # Panel 2: RL
    ax = axes[2]
    ax.set_title(f"RL (run {rl_run['run_id'][:8]})")
    ax1 = ax
    ax2 = ax1.twinx()
    ax1.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(rl_df["start_time"], rl_df["rl_net_battery_kw"], label="Net Batt kW", color="tab:green")
    ax1.plot(rl_df["start_time"], rl_df["export_kw"], label="Export kW", color="tab:red")
    ax2.plot(rl_df["start_time"], rl_df["rl_soc_percent"], label="SoC %", color="tab:orange")
    ax1.set_ylabel("kW")
    ax2.set_ylabel("SoC %")
    ax1.set_ylim(-max_abs_kw * 1.1, max_abs_kw * 1.1)
    ax2.set_ylim(soc_min * 0.9, soc_max * 1.1)

    # Panel 3: Oracle
    ax = axes[3]
    ax.set_title("Oracle")
    ax1 = ax
    ax2 = ax1.twinx()
    ax1.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(
        oracle_df["start_time"],
        oracle_df["oracle_net_battery_kw"],
        label="Net Batt kW",
        color="tab:green",
    )
    ax1.plot(oracle_df["start_time"], oracle_df["export_kw"], label="Export kW", color="tab:red")
    ax2.plot(
        oracle_df["start_time"],
        oracle_df["oracle_soc_percent"],
        label="SoC %",
        color="tab:orange",
    )
    ax1.set_ylabel("kW")
    ax2.set_ylabel("SoC %")
    ax1.set_ylim(-max_abs_kw * 1.1, max_abs_kw * 1.1)
    ax2.set_ylim(soc_min * 0.9, soc_max * 1.1)

    axes[-1].set_xlim(xmin, xmax)
    axes[-1].set_xlabel("Time")

    # Simple legend for combined quantities
    handles = [
        plt.Line2D([0], [0], color="tab:blue", label="Price"),
        plt.Line2D([0], [0], color="tab:green", label="Net Batt kW"),
        plt.Line2D([0], [0], color="tab:orange", label="SoC %"),
        plt.Line2D([0], [0], color="tab:red", label="Export kW"),
    ]
    fig.legend(handles=handles, loc="upper right")
    fig.tight_layout(rect=[0, 0, 0.98, 0.96])

    out_dir = Path("debug") / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mpc_rl_oracle_{day}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    print(f"[plot-day] Saved plot to {out_path}")

    # Try to open the image with the default viewer (best-effort).
    try:
        subprocess.Popen(["xdg-open", str(out_path)])
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
