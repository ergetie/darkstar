from __future__ import annotations

"""
Evaluate Oracle-guided Antares BC policy vs MPC cost (Rev 82).

Usage:
    PYTHONPATH=. ./venv/bin/python ml/eval_antares_oracle_bc_cost.py --days 10
"""

import argparse
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.policy.antares_rl_policy import AntaresRLPolicyOracleBC
from ml.simulation.env import AntaresMPCEnv


@dataclass
class BcRunInfo:
    run_id: str
    artifact_dir: str


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_bc_run(engine: LearningEngine) -> Optional[BcRunInfo]:
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, artifact_dir
                FROM antares_rl_runs
                WHERE algo = 'oracle_bc'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        return None
    return BcRunInfo(run_id=row[0], artifact_dir=row[1])


def _load_eval_days(engine: LearningEngine, max_days: int) -> List[str]:
    days: List[str] = []
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


def _run_bc_cost(day: str, policy: AntaresRLPolicyOracleBC) -> float:
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


def _maybe_run_oracle(day: str) -> Optional[float]:
    try:
        df = solve_optimal_schedule(day)
    except Exception:
        return None
    return float(df["oracle_slot_cost_sek"].sum())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Oracle-BC Antares policy vs MPC and Oracle costs.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of recent days to evaluate (default: 10).",
    )
    args = parser.parse_args()

    engine = _get_engine()
    bc_run = _load_latest_bc_run(engine)
    if bc_run is None:
        print("[oracle-bc-cost] No oracle_bc runs; train BC model first.")
        return 1

    days = _load_eval_days(engine, args.days)
    if not days:
        print("[oracle-bc-cost] No candidate days to evaluate.")
        return 1

    policy = AntaresRLPolicyOracleBC.load_from_dir(bc_run.artifact_dir)

    print("[oracle-bc-cost] Evaluating Oracle-BC policy vs MPC/Oracle:")
    print(f"  run_id:      {bc_run.run_id}")
    print(f"  artifact_dir:{bc_run.artifact_dir}")

    rows: List[Dict[str, Any]] = []
    for day in days:
        print(f"[oracle-bc-cost] Day {day}: running MPC, Oracle-BC, Oracle...")
        mpc_cost = _run_mpc_cost(day)
        bc_cost = _run_bc_cost(day, policy)
        oracle_cost = _maybe_run_oracle(day)
        rows.append(
            {
                "day": day,
                "mpc_cost": mpc_cost,
                "bc_cost": bc_cost,
                "oracle_cost": oracle_cost,
            }
        )

    df = pd.DataFrame(rows)
    print("\n[oracle-bc-cost] Per-day cost comparison (SEK):")
    for _, row in df.iterrows():
        day = row["day"]
        mpc = float(row["mpc_cost"])
        bc = float(row["bc_cost"])
        delta = bc - mpc
        oracle = row.get("oracle_cost")
        oracle_s = f"{oracle:8.2f}" if oracle is not None else "   n/a  "
        print(f"  {day}: MPC={mpc:8.2f}  BC={bc:8.2f}  ΔBC-M={delta:7.2f}  Oracle={oracle_s}")

    mpc_total = float(df["mpc_cost"].sum())
    bc_total = float(df["bc_cost"].sum())
    delta_total = bc_total - mpc_total
    oracle_sub = df["oracle_cost"].dropna()
    print("\n[oracle-bc-cost] Aggregate stats:")
    print(f"  MPC total:     {mpc_total:8.2f} SEK")
    print(f"  BC total:      {bc_total:8.2f} SEK")
    print(
        f"  ΔBC-MPC:       {delta_total:8.2f} SEK ({delta_total / mpc_total * 100:4.1f} % of MPC)"
    )
    if not oracle_sub.empty:
        oracle_total = float(oracle_sub.sum())
        print(f"  Oracle total (subset): {oracle_total:8.2f} SEK")
        print(f"  MPC - Oracle (subset): {mpc_total - oracle_total:8.2f} SEK")
        print(f"  BC  - Oracle (subset): {bc_total - oracle_total:8.2f} SEK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
