"""Evaluate RL v2 PPO policy vs MPC/Oracle (Rev 84, lab).

Usage:
    PYTHONPATH=. ./venv/bin/python ml/rl_v2/eval_ppo_v2_cost.py --days 10
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from stable_baselines3 import PPO

from learning import LearningEngine, get_learning_engine
from ml.benchmark.milp_solver import solve_optimal_schedule
from ml.rl_v2.contract import RlV2StateSpec
from ml.rl_v2.env_v2 import AntaresEnvV2
from ml.simulation.env import AntaresMPCEnv


@dataclass
class PpoV2RunInfo:
    run_id: str
    artifact_dir: str
    seq_len: int


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_ppo_v2_run(engine: LearningEngine) -> Optional[PpoV2RunInfo]:
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
    return PpoV2RunInfo(run_id=row[0], artifact_dir=row[1], seq_len=seq_len)


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


def _run_mpc_cost(day: str) -> tuple[float, float, float]:
    env = AntaresMPCEnv(config_path="config.yaml")
    env.reset(day)
    # SoC from planner schedule (projected_soc_percent) to avoid relying on
    # internal RL-only state.
    schedule = getattr(env, "_schedule", None)
    soc_start = 0.0
    soc_end = 0.0
    if schedule is not None:
        df = schedule.copy()
        if df.index.name in {"start_time", "slot_start"} and "start_time" not in df.columns:
            df = df.reset_index()
        if "projected_soc_percent" in df.columns and not df.empty:
            soc_vals = (
                pd.to_numeric(df["projected_soc_percent"], errors="coerce")
                .dropna()
                .astype(float)
            )
            if not soc_vals.empty:
                soc_start = float(soc_vals.iloc[0])
                soc_end = float(soc_vals.iloc[-1])

    total_reward = 0.0
    while True:
        result = env.step(action=None)
        total_reward += result.reward
        if result.done:
            break
    return -total_reward, soc_start, soc_end


def _run_ppo_v2_cost(day: str, model: PPO, spec: RlV2StateSpec) -> tuple[float, float, float]:
    env = AntaresEnvV2(config_path="config.yaml", seq_len=spec.seq_len)
    state = env.reset(day)
    total_reward = 0.0
    done = False
    soc_start = float(getattr(env, "_initial_soc_percent", 0.0))
    soc_end = soc_start
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
        total_reward += res.reward
        soc_end = float(res.info.get("soc_percent", soc_end))
        state = res.next_state
        done = res.done
    return -total_reward, soc_start, soc_end


def _maybe_run_oracle(day: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        df = solve_optimal_schedule(day)
    except Exception:
        return None, None, None
    cost = float(df["oracle_slot_cost_sek"].sum())
    soc = pd.to_numeric(df.get("oracle_soc_percent"), errors="coerce").dropna()
    if soc.empty:
        return cost, None, None
    return cost, float(soc.iloc[0]), float(soc.iloc[-1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare RL v2 PPO policy vs MPC and Oracle costs.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help="Number of recent days to evaluate (default: 10).",
    )
    args = parser.parse_args()

    engine = _get_engine()
    ppo_run = _load_latest_ppo_v2_run(engine)
    if ppo_run is None:
        print("[rl-v2-ppo-cost] No ppo_v2_seq runs; train PPO v2 model first.")
        return 1

    days = _load_eval_days(engine, args.days)
    if not days:
        print("[rl-v2-ppo-cost] No candidate days to evaluate.")
        return 1

    spec = RlV2StateSpec(seq_len=ppo_run.seq_len)
    model_path = f"{ppo_run.artifact_dir}/model.zip"
    model = PPO.load(model_path, device="cpu")

    print("[rl-v2-ppo-cost] Evaluating PPO v2 policy vs MPC/Oracle:")
    print(f"  run_id:      {ppo_run.run_id}")
    print(f"  artifact_dir:{ppo_run.artifact_dir}")

    rows: List[Dict[str, Any]] = []
    for day in days:
        print(f"[rl-v2-ppo-cost] Day {day}: running MPC, PPO v2, Oracle...")
        mpc_cost, mpc_soc_start, mpc_soc_end = _run_mpc_cost(day)
        ppo_cost, ppo_soc_start, ppo_soc_end = _run_ppo_v2_cost(day, model, spec)
        oracle_cost, oracle_soc_start, oracle_soc_end = _maybe_run_oracle(day)
        rows.append(
            {
                "day": day,
                "mpc_cost": mpc_cost,
                "ppo_cost": ppo_cost,
                "ppo_soc_start": ppo_soc_start,
                "ppo_soc_end": ppo_soc_end,
                "mpc_soc_start": mpc_soc_start,
                "mpc_soc_end": mpc_soc_end,
                "oracle_cost": oracle_cost,
                "oracle_soc_start": oracle_soc_start,
                "oracle_soc_end": oracle_soc_end,
            }
        )

    df = pd.DataFrame(rows)
    print("\n[rl-v2-ppo-cost] Per-day cost comparison (SEK):")
    for _, row in df.iterrows():
        day = row["day"]
        mpc = float(row["mpc_cost"])
        ppo = float(row["ppo_cost"])
        delta = ppo - mpc
        ppo_soc_start = float(row["ppo_soc_start"])
        ppo_soc_end = float(row["ppo_soc_end"])
        mpc_soc_start = float(row.get("mpc_soc_start", float("nan")))
        mpc_soc_end = float(row.get("mpc_soc_end", float("nan")))
        oracle = row.get("oracle_cost")
        oracle_soc_start = row.get("oracle_soc_start")
        oracle_soc_end = row.get("oracle_soc_end")
        oracle_s = f"{oracle:8.2f}" if oracle is not None else "   n/a  "
        oracle_soc_s = (
            f"{float(oracle_soc_start):5.1f}->{float(oracle_soc_end):5.1f}"
            if oracle_soc_start is not None and oracle_soc_end is not None
            else "  n/a "
        )
        print(
            f"  {day}: MPC={mpc:8.2f}  PPOv2={ppo:8.2f}  ΔPPOv2-M={delta:7.2f}  "
            f"SoC_MPC={mpc_soc_start:5.1f}->{mpc_soc_end:5.1f}  "
            f"SoC_PPO={ppo_soc_start:5.1f}->{ppo_soc_end:5.1f}  "
            f"SoC_Oracle={oracle_soc_s}  Oracle={oracle_s}"
        )

    mpc_total = float(df["mpc_cost"].sum())
    ppo_total = float(df["ppo_cost"].sum())
    delta_total = ppo_total - mpc_total
    oracle_sub = df["oracle_cost"].dropna()
    ppo_soc_diff = (df["ppo_soc_end"] - df["ppo_soc_start"]).abs()
    mpc_soc_diff = (df["mpc_soc_end"] - df["mpc_soc_start"]).abs()
    oracle_soc_diff = (
        (df["oracle_soc_end"] - df["oracle_soc_start"]).abs()
        if "oracle_soc_start" in df.columns
        else pd.Series(dtype=float)
    )
    print("\n[rl-v2-ppo-cost] Aggregate stats:")
    print(f"  MPC total:      {mpc_total:8.2f} SEK")
    print(f"  PPO v2 total:   {ppo_total:8.2f} SEK")
    print(
        f"  ΔPPOv2-MPC:     {delta_total:8.2f} SEK "
        f"({delta_total / mpc_total * 100:4.1f} % of MPC)"
    )
    if not oracle_sub.empty:
        oracle_total = float(oracle_sub.sum())
        print(f"  Oracle total (subset): {oracle_total:8.2f} SEK")
        print(f"  MPC - Oracle (subset): {mpc_total - oracle_total:8.2f} SEK")
        print(f"  PPOv2 - Oracle (subset): {ppo_total - oracle_total:8.2f} SEK")
    print(
        f"  Avg |ΔSoC| start→end: "
        f"MPC={float(mpc_soc_diff.mean()):5.1f} %, "
        f"PPOv2={float(ppo_soc_diff.mean()):5.1f} %, "
        f"Oracle={float(oracle_soc_diff.mean()) if not oracle_soc_diff.empty else float('nan'):5.1f} %"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
