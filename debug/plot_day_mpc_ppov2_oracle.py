from __future__ import annotations

"""
Plot MPC vs PPO v2 vs Oracle actions for a single day (RL v2 lab).

Usage:
    PYTHONPATH=. ./venv/bin/python debug/plot_day_mpc_ppov2_oracle.py --day 2025-11-25
"""

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from stable_baselines3 import PPO

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.rl_v2.contract import RlV2StateSpec
from ml.rl_v2.env_v2 import AntaresEnvV2
from ml.simulation.data_loader import SimulationDataLoader
from ml.simulation.env import AntaresMPCEnv


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_ppo_v2_run(engine: LearningEngine) -> Optional[Dict[str, Any]]:
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, artifact_dir, hyperparams_json
                FROM antares_rl_runs
                WHERE algo = 'ppo_v2_seq'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        return None
    hyper = json.loads(row[2]) if row[2] else {}
    seq_len = int(hyper.get("seq_len", 48))
    return {
        "run_id": row[0],
        "artifact_dir": row[1],
        "seq_len": seq_len,
    }


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
    schedule["net_battery_kw"] = schedule["battery_charge_kw"] - schedule["battery_discharge_kw"]
    schedule["soc_percent"] = schedule.get("projected_soc_percent", 0.0).astype(float)

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


def _build_ppov2_schedule(day: str, model: PPO, spec: RlV2StateSpec) -> pd.DataFrame:
    env = AntaresEnvV2(config_path="config.yaml", seq_len=spec.seq_len)
    state = env.reset(day)

    rows: List[Dict[str, Any]] = []
    done = False
    idx = 0
    while not done:
        action, _ = model.predict(state, deterministic=True)
        action = np.asarray(action, dtype=float).flatten()
        charge_kw = max(0.0, float(action[0])) if action.size >= 1 else 0.0
        discharge_kw = max(0.0, float(action[1])) if action.size >= 2 else 0.0

        res = env.step(
            {
                "battery_charge_kw": charge_kw,
                "battery_discharge_kw": discharge_kw,
            }
        )

        info = res.info
        rows.append(
            {
                "index": idx,
                "slot_hours": float(info.get("slot_hours", 0.25)),
                "import_price": float(info.get("import_price_sek_kwh", 0.0)),
                "export_price": float(info.get("export_price_sek_kwh", 0.0)),
                "load_kwh": float(info.get("load_kwh", 0.0)),
                "pv_kwh": float(info.get("pv_kwh", 0.0)),
                "grid_import_kwh": float(info.get("grid_import_kwh", 0.0)),
                "grid_export_kwh": float(info.get("grid_export_kwh", 0.0)),
                "ppo_charge_kw": float(info.get("battery_charge_kw", 0.0)),
                "ppo_discharge_kw": float(info.get("battery_discharge_kw", 0.0)),
                "ppo_net_battery_kw": float(info.get("battery_charge_kw", 0.0))
                - float(info.get("battery_discharge_kw", 0.0)),
                "ppo_soc_percent": float(info.get("soc_percent", 0.0)),
            }
        )

        state = res.next_state
        done = res.done
        idx += 1

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    loader = SimulationDataLoader("config.yaml")
    tz = loader.timezone
    start_ts = tz.localize(pd.Timestamp(day))
    df["start_time"] = start_ts + pd.to_timedelta(df["index"] * 15, unit="m")
    df["load_kw"] = df["load_kwh"] * 4.0
    df["pv_kw"] = df["pv_kwh"] * 4.0
    df["export_kw"] = df["grid_export_kwh"] * 4.0
    return df


def _build_oracle_schedule(day: str) -> pd.DataFrame:
    df = solve_optimal_schedule(day)
    df = df.copy()
    df["start_time"] = pd.to_datetime(df["slot_start"])
    df = df.sort_values("start_time")

    slot_hours = df.get("slot_hours", 0.25).astype(float).replace(0.0, 0.25)
    df["oracle_charge_kw"] = df["oracle_charge_kwh"].astype(float) / slot_hours
    df["oracle_discharge_kw"] = df["oracle_discharge_kwh"].astype(float) / slot_hours
    df["oracle_net_battery_kw"] = df["oracle_charge_kw"] - df["oracle_discharge_kw"]
    df["oracle_soc_percent"] = df.get("oracle_soc_percent", 0.0).astype(float)
    df["import_price"] = df.get("import_price_sek_kwh", 0.0).astype(float)
    df["export_price"] = df.get("export_price_sek_kwh", df["import_price"]).astype(float)
    df["export_kw"] = df["oracle_grid_export_kwh"].astype(float) / slot_hours
    return df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot MPC vs PPO v2 vs Oracle battery actions for a single day.",
    )
    parser.add_argument("--day", required=True, help="Day to plot (YYYY-MM-DD)")
    args = parser.parse_args()

    day = args.day
    engine = _get_engine()
    ppo_run = _load_latest_ppo_v2_run(engine)
    if ppo_run is None:
        raise SystemExit("[plot-ppov2-day] No ppo_v2_seq runs; train PPO v2 first.")

    spec = RlV2StateSpec(seq_len=ppo_run["seq_len"])
    model_path = Path(ppo_run["artifact_dir"]) / "model.zip"
    model = PPO.load(model_path.as_posix(), device="cpu")

    print(f"[plot-ppov2-day] Building MPC schedule for {day}...")
    mpc_df = _build_mpc_schedule(day)
    print(
        f"[plot-ppov2-day] Building PPO v2 schedule for {day} " f"(run {ppo_run['run_id'][:8]})..."
    )
    ppo_df = _build_ppov2_schedule(day, model, spec)
    print(f"[plot-ppov2-day] Solving Oracle schedule for {day}...")
    oracle_df = _build_oracle_schedule(day)

    day_ts = pd.Timestamp(day)
    tz = mpc_df["start_time"].dt.tz if mpc_df["start_time"].dt.tz is not None else None
    if tz is not None:
        day_start = day_ts.tz_localize(tz)
    else:
        day_start = day_ts
    day_end = day_start + pd.Timedelta(days=1)

    mpc_df = mpc_df[(mpc_df["start_time"] >= day_start) & (mpc_df["start_time"] < day_end)].copy()
    ppo_df = ppo_df[(ppo_df["start_time"] >= day_start) & (ppo_df["start_time"] < day_end)].copy()
    oracle_df = oracle_df[
        (oracle_df["start_time"] >= day_start) & (oracle_df["start_time"] < day_end)
    ].copy()

    xmin = day_start
    xmax = day_end

    all_price = pd.concat(
        [mpc_df["import_price"], ppo_df["import_price"], oracle_df["import_price"]]
    )
    price_min, price_max = float(all_price.min()), float(all_price.max())

    all_net_batt = pd.concat(
        [
            mpc_df["net_battery_kw"],
            ppo_df["ppo_net_battery_kw"],
            oracle_df["oracle_net_battery_kw"],
        ]
    )
    max_abs_kw = float(all_net_batt.abs().max())
    if max_abs_kw <= 0.0:
        max_abs_kw = 1.0

    soc_vals = pd.concat(
        [mpc_df["soc_percent"], ppo_df["ppo_soc_percent"], oracle_df["oracle_soc_percent"]]
    )
    soc_min, soc_max = float(soc_vals.min()), float(soc_vals.max())

    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(12, 10))
    fig.suptitle(f"MPC vs PPO v2 vs Oracle — {day}")

    ax = axes[0]
    ax2 = ax.twinx()
    ax.plot(mpc_df["start_time"], mpc_df["import_price"], label="Price", color="tab:blue")
    ax2.plot(mpc_df["start_time"], mpc_df["load_kw"], label="Load kW", color="tab:gray")
    ax2.plot(mpc_df["start_time"], mpc_df["pv_kw"], label="PV kW", color="tab:green")
    ax.set_ylabel("Price (SEK/kWh)")
    ax2.set_ylabel("kW")
    ax.set_ylim(price_min * 0.95, price_max * 1.05)

    ax = axes[1]
    ax.set_title("MPC")
    ax1 = ax
    ax2 = ax1.twinx()
    ax1.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(
        mpc_df["start_time"],
        mpc_df["net_battery_kw"],
        label="Net Batt kW",
        color="tab:green",
    )
    ax1.plot(mpc_df["start_time"], mpc_df["export_kw"], label="Export kW", color="tab:red")
    ax2.plot(mpc_df["start_time"], mpc_df["soc_percent"], label="SoC %", color="tab:orange")
    ax1.set_ylabel("kW")
    ax2.set_ylabel("SoC %")
    ax1.set_ylim(-max_abs_kw * 1.1, max_abs_kw * 1.1)
    ax2.set_ylim(soc_min * 0.9, soc_max * 1.1)

    ax = axes[2]
    ax.set_title(f"PPO v2 (run {ppo_run['run_id'][:8]})")
    ax1 = ax
    ax2 = ax1.twinx()
    ax1.axhline(0.0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.plot(
        ppo_df["start_time"],
        ppo_df["ppo_net_battery_kw"],
        label="Net Batt kW",
        color="tab:green",
    )
    ax1.plot(ppo_df["start_time"], ppo_df["export_kw"], label="Export kW", color="tab:red")
    ax2.plot(
        ppo_df["start_time"],
        ppo_df["ppo_soc_percent"],
        label="SoC %",
        color="tab:orange",
    )
    ax1.set_ylabel("kW")
    ax2.set_ylabel("SoC %")
    ax1.set_ylim(-max_abs_kw * 1.1, max_abs_kw * 1.1)
    ax2.set_ylim(soc_min * 0.9, soc_max * 1.1)

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
    out_path = out_dir / f"mpc_ppov2_oracle_{day}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    print(f"[plot-ppov2-day] Saved plot to {out_path}")

    try:
        subprocess.Popen(["xdg-open", str(out_path)])
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
