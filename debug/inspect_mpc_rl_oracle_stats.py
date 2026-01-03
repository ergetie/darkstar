from __future__ import annotations

"""
Quick text stats for MPC vs RL vs Oracle for a single day.

Usage:
    PYTHONPATH=. python debug/inspect_mpc_rl_oracle_stats.py --day 2025-11-20
"""

import argparse
from typing import Any

import pandas as pd
from learning import LearningEngine, get_learning_engine

from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.policy.antares_rl_policy import AntaresRLPolicyV1
from ml.simulation.env import AntaresMPCEnv


def _load_latest_rl_run(engine: LearningEngine) -> dict[str, str]:
    import sqlite3

    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, artifact_dir
                FROM antares_rl_runs
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        raise SystemExit("[inspect] No antares_rl_runs rows; train RL first.")
    return {"run_id": row[0], "artifact_dir": row[1]}


def _build_mpc_df(day: str) -> pd.DataFrame:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()
    schedule["start_time"] = pd.to_datetime(schedule["start_time"])
    schedule = schedule.sort_values("start_time")
    schedule["import_price"] = schedule["import_price_sek_kwh"].astype(float)
    schedule["battery_charge_kw"] = schedule.get(
        "battery_charge_kw", schedule.get("charge_kw", 0.0)
    ).astype(float)
    schedule["battery_discharge_kw"] = schedule.get("battery_discharge_kw", 0.0).astype(float)
    schedule["net_batt_kw"] = schedule["battery_charge_kw"] - schedule["battery_discharge_kw"]
    return schedule[["start_time", "import_price", "net_batt_kw"]]


def _build_rl_df(day: str, policy: AntaresRLPolicyV1) -> pd.DataFrame:
    env = AntaresMPCEnv(config_path="config.yaml")
    state = env.reset(day)
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()

    rows: list[dict[str, Any]] = []
    idx = 0
    while True:
        row0 = schedule.iloc[idx]
        start_time = pd.to_datetime(row0["start_time"])
        import_price = float(row0.get("import_price_sek_kwh", 0.0) or 0.0)

        action = policy.predict(state)
        result = env.step(action=action)

        eff_net = float(
            result.info.get(
                "net_battery_kw",
                float(result.info.get("battery_charge_kw", 0.0))
                - float(result.info.get("battery_discharge_kw", 0.0)),
            )
        )

        rows.append(
            {
                "start_time": start_time,
                "import_price": import_price,
                "net_batt_kw": eff_net,
            }
        )

        state = result.next_state
        idx += 1
        if result.done or idx >= len(schedule):
            break

    df = pd.DataFrame(rows)
    return df.sort_values("start_time")


def _build_oracle_df(day: str) -> pd.DataFrame:
    df = solve_optimal_schedule(day)
    df = df.copy()
    df["start_time"] = pd.to_datetime(df["slot_start"])
    df = df.sort_values("start_time")
    df["import_price"] = df["import_price_sek_kwh"].astype(float)
    # Oracle outputs charge/discharge in kWh per slot; convert to kW.
    slot_h = df.get("slot_hours")
    if slot_h is None:
        slot_h = pd.Series(0.25, index=df.index)
    slot_h = slot_h.replace(0, 0.25).astype(float)
    charge_kw = df["oracle_charge_kwh"].astype(float) / slot_h
    discharge_kw = df["oracle_discharge_kwh"].astype(float) / slot_h
    # Convention: positive = charging, negative = discharging.
    df["net_batt_kw"] = charge_kw - discharge_kw
    return df[["start_time", "import_price", "net_batt_kw"]]


def _restrict_to_day(df: pd.DataFrame, day: str) -> pd.DataFrame:
    if df.empty:
        return df
    day_ts = pd.Timestamp(day)
    if df["start_time"].dt.tz is not None:
        day_start = day_ts.tz_localize(df["start_time"].dt.tz)
    else:
        day_start = day_ts
    day_end = day_start + pd.Timedelta(days=1)
    mask = (df["start_time"] >= day_start) & (df["start_time"] < day_end)
    return df[mask].copy()


def _summarize(label: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"[{label}] empty")
        return
    prices = df["import_price"]
    p_lo, p_med, p_hi = prices.quantile([0.25, 0.5, 0.75]).tolist()
    print(f"[{label}] price q: 25%={p_lo:.3f}, 50%={p_med:.3f}, 75%={p_hi:.3f}")

    def stats(mask_name: str, mask: pd.Series) -> None:
        sub = df[mask]
        if sub.empty:
            print(f"  {mask_name}: 0 slots")
            return
        print(
            f"  {mask_name}: {len(sub):2d} slots, "
            f"mean price={sub['import_price'].mean():.3f}, "
            f"mean net_batt_kw={sub['net_batt_kw'].mean():+.3f}"
        )

    stats("charge (net>0)", df["net_batt_kw"] > 0.05)
    stats("discharge (net<-0.05)", df["net_batt_kw"] < -0.05)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print simple MPC/RL/Oracle net-battery vs price stats for a day.",
    )
    parser.add_argument("--day", required=True, help="Day to inspect (YYYY-MM-DD)")
    args = parser.parse_args()

    engine = get_learning_engine()
    rl_run = _load_latest_rl_run(engine)
    policy = AntaresRLPolicyV1.load_from_dir(rl_run["artifact_dir"])

    day = args.day
    print(f"[inspect] Day: {day}, RL run: {rl_run['run_id']}")

    mpc_df = _restrict_to_day(_build_mpc_df(day), day)
    rl_df = _restrict_to_day(_build_rl_df(day, policy), day)
    oracle_df = _restrict_to_day(_build_oracle_df(day), day)

    print("\nMPC:")
    _summarize("MPC", mpc_df)
    print("\nRL:")
    _summarize("RL", rl_df)
    print("\nOracle:")
    _summarize("Oracle", oracle_df)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
