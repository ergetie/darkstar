from __future__ import annotations

"""
Evaluate the Antares v1 policy against MPC actions in AntaresMPCEnv.

This helper reloads the latest antares_policy_runs entry, runs the policy
over a sample of days, and compares its predicted actions to the MPC
schedule actions (MAE/RMSE per target).
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from learning import LearningEngine, get_learning_engine
from ml.policy.antares_policy import AntaresPolicyV1
from ml.simulation.env import AntaresMPCEnv


TARGET_NAMES = ["battery_charge_kw", "battery_discharge_kw", "export_kw"]


@dataclass
class PolicyRunInfo:
    run_id: str
    models_dir: Path


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_policy_run(engine: LearningEngine) -> PolicyRunInfo | None:
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, models_dir
                FROM antares_policy_runs
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None

    if row is None:
        return None
    return PolicyRunInfo(run_id=row[0], models_dir=Path(row[1]))


def _load_eval_days(engine: LearningEngine, max_days: int = 20) -> List[str]:
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


def _ascii_bar(ratio: float, width: int = 20) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = int(round(ratio * width))
    return "█" * filled + "·" * (width - filled)


def evaluate_policy(policy: AntaresPolicyV1, days: List[str]) -> Dict[str, Dict[str, float]]:
    env = AntaresMPCEnv(config_path="config.yaml")
    errors: Dict[str, List[float]] = {name: [] for name in TARGET_NAMES}
    scales: Dict[str, List[float]] = {name: [] for name in TARGET_NAMES}

    for day in days:
        try:
            state = env.reset(day)
        except Exception:
            continue

        schedule = env._schedule  # type: ignore[attr-defined]
        if schedule is None or schedule.empty:
            continue

        for _, row in schedule.reset_index().iterrows():
            state_vec = env._build_state_vector(row)  # type: ignore[attr-defined]
            preds = policy.predict(state_vec)

            true_charge = float(
                row.get("battery_charge_kw")
                or row.get("charge_kw")
                or 0.0
            )
            true_discharge = float(row.get("battery_discharge_kw") or 0.0)
            true_export = float(row.get("export_kw") or 0.0)

            errors["battery_charge_kw"].append(preds["battery_charge_kw"] - true_charge)
            errors["battery_discharge_kw"].append(
                preds["battery_discharge_kw"] - true_discharge
            )
            errors["export_kw"].append(preds["export_kw"] - true_export)

            scales["battery_charge_kw"].append(true_charge)
            scales["battery_discharge_kw"].append(true_discharge)
            scales["export_kw"].append(true_export)

    metrics: Dict[str, Dict[str, float]] = {}
    for name in TARGET_NAMES:
        err = np.array(errors[name], dtype=float)
        scale = np.array(scales[name], dtype=float)
        if err.size == 0:
            metrics[name] = {"mae": None, "rmse": None, "mean_true": None, "rel": None}
            continue

        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err**2)))
        mean_true = float(np.mean(np.abs(scale))) if scale.size > 0 else 0.0
        rel = mae / mean_true if mean_true > 0 else 0.0

        metrics[name] = {
            "mae": mae,
            "rmse": rmse,
            "mean_true": mean_true,
            "rel": rel,
        }

    return metrics


def main() -> int:
    engine = _get_engine()
    run = _load_latest_policy_run(engine)
    if run is None:
        print("[policy-eval] No antares_policy_runs entries found; train policy first.")
        return 1

    print("[policy-eval] Evaluating latest Antares v1 policy:")
    print(f"  run_id:      {run.run_id}")
    print(f"  models_dir:  {run.models_dir}")

    policy = AntaresPolicyV1.load_from_dir(run.models_dir)
    days = _load_eval_days(engine)
    if not days:
        print("[policy-eval] No evaluation days; check data_quality_daily.")
        return 1

    print(f"[policy-eval] Evaluation days: {days[0]} → {days[-1]} ({len(days)} days)")
    metrics = evaluate_policy(policy, days)

    print("\n[policy-eval] Per-target imitation quality:")
    for name, m in metrics.items():
        mae = m["mae"]
        mean_true = m["mean_true"]
        rel = m["rel"]
        if mae is None or mean_true is None or rel is None:
            print(f"  {name:20s} (no samples)")
            continue
        bar = _ascii_bar(min(1.0, rel))
        print(
            f"  {name:20s} MAE={mae:0.4f}  mean={mean_true:0.4f}  rel={rel:0.2f}  {bar}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

