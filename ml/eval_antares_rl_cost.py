from __future__ import annotations

"""
Evaluate Antares RL policy vs MPC cost (Rev 76).

Usage (from project root):
    PYTHONPATH=. python ml/eval_antares_rl_cost.py --days 10
"""

import argparse
import sqlite3
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from learning import LearningEngine, get_learning_engine

from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.policy.antares_rl_policy import AntaresRLPolicyV1
from ml.simulation.env import AntaresMPCEnv


@dataclass
class RlRunInfo:
    run_id: str
    artifact_dir: str


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_rl_run(engine: LearningEngine) -> RlRunInfo | None:
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
        return None
    return RlRunInfo(run_id=row[0], artifact_dir=row[1])


def _load_eval_days(engine: LearningEngine, max_days: int) -> list[str]:
    days: list[str] = []
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            rows = conn.execute(
                """
                SELECT date
                FROM data_quality_daily
                WHERE status IN ('clean', 'mask_battery')
                ORDER BY date DESC
                LIMIT ?
                """,
                (max_days,),
            ).fetchall()
    except sqlite3.Error:
        rows = []
    for (d,) in rows:
        days.append(d)
    return list(reversed(days))


def _run_mpc_cost(day: str) -> float:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    total_reward = 0.0
    while True:
        result = env.step(action=None)
        total_reward += result.reward
        if result.done:
            break
    return -total_reward


def _run_rl_cost(day: str, policy: AntaresRLPolicyV1) -> float:
    env = AntaresMPCEnv(config_path="config.yaml")
    state = env.reset(day)
    total_reward = 0.0
    while True:
        action = policy.predict(state)
        result = env.step(action=action)
        total_reward += result.reward
        state = result.next_state
        if result.done:
            break
    return -total_reward


def _maybe_run_oracle(day: str) -> float | None:
    try:
        df = solve_optimal_schedule(day)
    except Exception:
        return None
    return float(df["oracle_slot_cost_sek"].sum())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Antares RL policy, MPC, and Oracle costs over historical days.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of recent days to evaluate (default: 10).",
    )
    args = parser.parse_args()

    engine = _get_engine()
    run = _load_latest_rl_run(engine)
    if run is None:
        print("[rl-cost] No antares_rl_runs entries found; train RL policy first.")
        return 1

    print("[rl-cost] Evaluating Antares RL policy cost vs MPC/Oracle:")
    print(f"  run_id:      {run.run_id}")
    print(f"  artifact_dir:{run.artifact_dir}")

    days = _load_eval_days(engine, max_days=args.days)
    if not days:
        print("[rl-cost] No evaluation days; check data_quality_daily.")
        return 1

    policy = AntaresRLPolicyV1.load_from_dir(run.artifact_dir)

    records: list[dict[str, Any]] = []

    for d in days:
        print(f"[rl-cost] Day {d}: running MPC, RL, Oracle...")
        mpc_cost = _run_mpc_cost(d)
        rl_cost = _run_rl_cost(d, policy)
        oracle_cost = _maybe_run_oracle(d)

        records.append(
            {
                "date": d,
                "mpc_cost": mpc_cost,
                "rl_cost": rl_cost,
                "oracle_cost": oracle_cost,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        print("[rl-cost] No cost records; aborting.")
        return 1

    df = df.replace([np.inf, -np.inf], np.nan)
    valid_mask = df[["mpc_cost", "rl_cost"]].notna().all(axis=1)
    if not valid_mask.any():
        print("[rl-cost] All MPC/RL costs are NaN/inf; nothing to report.")
        return 1
    df_valid = df[valid_mask].copy()

    print("\n[rl-cost] Per-day cost comparison (SEK):")
    for _, row in df_valid.iterrows():
        d = row["date"]
        mpc = float(row["mpc_cost"])
        rl = float(row["rl_cost"])
        oracle = row.get("oracle_cost")

        delta_rm = rl - mpc
        line = f"  {d}: MPC={mpc:8.2f}  RL={rl:8.2f}  ΔRL-M={delta_rm:7.2f}"
        if oracle is not None:
            line += f"  Oracle={float(oracle):8.2f}"
        print(line)

    print("\n[rl-cost] Aggregate stats:")
    mpc_total = float(df_valid["mpc_cost"].sum())
    rl_total = float(df_valid["rl_cost"].sum())
    delta_total = rl_total - mpc_total
    rel = (delta_total / mpc_total * 100.0) if mpc_total != 0 else 0.0
    print(f"  MPC total:    {mpc_total:8.2f} SEK")
    print(f"  RL total:     {rl_total:8.2f} SEK")
    print(f"  ΔRL-MPC:      {delta_total:8.2f} SEK ({rel:0.1f} % of MPC)")

    oracle_vals = df_valid["oracle_cost"].dropna()
    if not oracle_vals.empty:
        oracle_total = float(oracle_vals.sum())
        mask = df_valid["oracle_cost"].notna()
        mpc_on_oracle = float(df_valid.loc[mask, "mpc_cost"].sum())
        rl_on_oracle = float(df_valid.loc[mask, "rl_cost"].sum())
        print(f"  Oracle total (subset): {oracle_total:8.2f} SEK")
        print(f"  MPC - Oracle (subset): {mpc_on_oracle - oracle_total:8.2f} SEK")
        print(f"  RL - Oracle (subset):  {rl_on_oracle - oracle_total:8.2f} SEK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
