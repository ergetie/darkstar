"""Evaluate BC v2 (sequence) policy vs MPC/Oracle (Rev 84).

Usage:
    PYTHONPATH=. ./venv/bin/python ml/rl_v2/eval_bc_v2_cost.py --days 10
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.rl_v2.contract import RlV2StateSpec
from ml.rl_v2.env_v2 import AntaresEnvV2
from ml.simulation.env import AntaresMPCEnv


class OracleBcV2Net(nn.Module):
    def __init__(self, in_dim: int, hidden_dim: int, out_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@dataclass
class BcV2RunInfo:
    run_id: str
    artifact_dir: str
    seq_len: int
    hidden_dim: int
    action_dim: int


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_bc_v2_run(engine: LearningEngine) -> Optional[BcV2RunInfo]:
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, artifact_dir, hyperparams_json, metrics_json
                FROM antares_rl_runs
                WHERE algo = 'oracle_bc_v2_seq'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        return None
    hyper = json.loads(row[2]) if row[2] else {}
    metrics = json.loads(row[3]) if row[3] else {}
    seq_len = int(hyper.get("seq_len", 48))
    hidden_dim = int(hyper.get("hidden_dim", 128))
    action_dim = int(metrics.get("output_dim", 3))
    return BcV2RunInfo(
        run_id=row[0],
        artifact_dir=row[1],
        seq_len=seq_len,
        hidden_dim=hidden_dim,
        action_dim=action_dim,
    )


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
    for d, in rows:
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


def _run_bc_v2_cost(day: str, model: OracleBcV2Net, spec: RlV2StateSpec) -> float:
    env = AntaresEnvV2(config_path="config.yaml", seq_len=spec.seq_len)
    state = env.reset(day)
    total_reward = 0.0
    done = False
    model.eval()
    while not done:
        x = torch.from_numpy(state.astype(np.float32)).unsqueeze(0)
        with torch.no_grad():
            pred = model(x)[0]
        charge_kw = max(0.0, float(pred[0]))
        discharge_kw = max(0.0, float(pred[1]))
        export_kw = max(0.0, float(pred[2]))
        res = env.step(
            {
                "battery_charge_kw": charge_kw,
                "battery_discharge_kw": discharge_kw,
                "export_kw": export_kw,
            }
        )
        total_reward += res.reward
        state = res.next_state
        done = res.done
    return -total_reward


def _maybe_run_oracle(day: str) -> Optional[float]:
    try:
        df = solve_optimal_schedule(day)
    except Exception:
        return None
    return float(df["oracle_slot_cost_sek"].sum())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Oracle-BC v2 sequence policy vs MPC and Oracle costs.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of recent days to evaluate (default: 10).",
    )
    args = parser.parse_args()

    engine = _get_engine()
    bc_run = _load_latest_bc_v2_run(engine)
    if bc_run is None:
        print("[oracle-bc-v2-cost] No oracle_bc_v2_seq runs; train BC v2 model first.")
        return 1

    days = _load_eval_days(engine, args.days)
    if not days:
        print("[oracle-bc-v2-cost] No candidate days to evaluate.")
        return 1

    spec = RlV2StateSpec(seq_len=bc_run.seq_len)
    model = OracleBcV2Net(
        in_dim=spec.flat_dim,
        hidden_dim=bc_run.hidden_dim,
        out_dim=bc_run.action_dim,
    )
    model_path = f"{bc_run.artifact_dir}/model.pt"
    state_dict = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state_dict)

    print("[oracle-bc-v2-cost] Evaluating Oracle-BC v2 policy vs MPC/Oracle:")
    print(f"  run_id:      {bc_run.run_id}")
    print(f"  artifact_dir:{bc_run.artifact_dir}")

    rows: List[Dict[str, Any]] = []
    for day in days:
        print(f"[oracle-bc-v2-cost] Day {day}: running MPC, Oracle-BC v2, Oracle...")
        mpc_cost = _run_mpc_cost(day)
        bc_cost = _run_bc_v2_cost(day, model, spec)
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
    print("\n[oracle-bc-v2-cost] Per-day cost comparison (SEK):")
    for _, row in df.iterrows():
        day = row["day"]
        mpc = float(row["mpc_cost"])
        bc = float(row["bc_cost"])
        delta = bc - mpc
        oracle = row.get("oracle_cost")
        oracle_s = f"{oracle:8.2f}" if oracle is not None else "   n/a  "
        print(
            f"  {day}: MPC={mpc:8.2f}  BCv2={bc:8.2f}  ΔBCv2-M={delta:7.2f}  Oracle={oracle_s}"
        )

    mpc_total = float(df["mpc_cost"].sum())
    bc_total = float(df["bc_cost"].sum())
    delta_total = bc_total - mpc_total
    oracle_sub = df["oracle_cost"].dropna()
    print("\n[oracle-bc-v2-cost] Aggregate stats:")
    print(f"  MPC total:     {mpc_total:8.2f} SEK")
    print(f"  BC v2 total:   {bc_total:8.2f} SEK")
    print(
        f"  ΔBCv2-MPC:     {delta_total:8.2f} SEK "
        f"({delta_total / mpc_total * 100:4.1f} % of MPC)"
    )
    if not oracle_sub.empty:
        oracle_total = float(oracle_sub.sum())
        print(f"  Oracle total (subset): {oracle_total:8.2f} SEK")
        print(f"  MPC - Oracle (subset): {mpc_total - oracle_total:8.2f} SEK")
        print(f"  BCv2 - Oracle (subset): {bc_total - oracle_total:8.2f} SEK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
