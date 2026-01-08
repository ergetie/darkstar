"""
Evaluation: Antares V1 policy benchmarking.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from learning import LearningEngine, get_learning_engine

from ml.api import get_antares_slots
from ml.train_antares import TARGET_COLUMNS, _build_feature_frame


@dataclass
class RunInfo:
    run_id: str
    dataset_version: str
    train_start_date: str
    train_end_date: str
    val_start_date: str | None
    val_end_date: str | None
    artifact_dir: Path


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_latest_run(db_path: str) -> RunInfo | None:
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        row = conn.execute(
            """
            SELECT run_id,
                   dataset_version,
                   train_start_date,
                   train_end_date,
                   val_start_date,
                   val_end_date,
                   artifact_dir
            FROM antares_training_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    return RunInfo(
        run_id=row[0],
        dataset_version=row[1],
        train_start_date=row[2],
        train_end_date=row[3],
        val_start_date=row[4],
        val_end_date=row[5],
        artifact_dir=Path(row[6]),
    )


def _load_models(run: RunInfo) -> dict[str, lgb.Booster]:
    models: dict[str, lgb.Booster] = {}
    for target in TARGET_COLUMNS:
        path = run.artifact_dir / f"{target}.lgb"
        if not path.exists():
            continue
        models[target] = lgb.Booster(model_file=str(path))
    return models


def _filter_validation_window(
    df: pd.DataFrame,
    run: RunInfo,
) -> pd.DataFrame:
    if not run.val_start_date or not run.val_end_date:
        return df.iloc[0:0].copy()

    start = datetime.fromisoformat(run.val_start_date).date()
    end = datetime.fromisoformat(run.val_end_date).date()

    data = df.copy()
    data["episode_date_dt"] = pd.to_datetime(data["episode_date"]).dt.date
    mask = (data["episode_date_dt"] >= start) & (data["episode_date_dt"] <= end)
    return data[mask].copy()


def _ascii_bar(ratio: float, width: int = 20) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return "█" * filled + "·" * (width - filled)


def evaluate_run(run: RunInfo) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    df = get_antares_slots(dataset_version=run.dataset_version)
    if df.empty:
        return {}, {}

    data, feature_cols = _build_feature_frame(df)
    val_df = _filter_validation_window(data, run)
    if val_df.empty:
        return {}, {}

    metrics: dict[str, dict[str, float]] = {}

    for target in TARGET_COLUMNS:
        if target not in data.columns:
            continue

        subset = val_df[val_df[target].notnull()].copy()
        if subset.empty:
            continue

        X = subset[feature_cols].apply(pd.to_numeric, errors="coerce")
        y_true = subset[target].astype(float)
        mask = ~y_true.isna() & ~X.isna().any(axis=1)
        X = X[mask]
        y_true = y_true[mask]
        if len(X) == 0:
            continue

        models = _load_models(run)
        booster = models.get(target)
        if booster is None:
            continue

        y_pred = booster.predict(X)
        err = y_pred - y_true.to_numpy()
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err**2)))
        mean_true = float(y_true.mean())

        metrics[target] = {
            "mae": mae,
            "rmse": rmse,
            "mean_true": mean_true,
        }

    cost_stats: dict[str, float] = {}
    if {"import_kwh", "export_kwh", "import_price_sek_kwh", "export_price_sek_kwh"}.issubset(
        val_df.columns
    ):
        import_cost = val_df["import_kwh"].astype(float) * val_df["import_price_sek_kwh"].astype(
            float
        )
        export_rev = val_df["export_kwh"].astype(float) * val_df["export_price_sek_kwh"].astype(
            float
        )
        slot_cost = import_cost - export_rev
        cost_stats = {
            "baseline_mean_cost_per_slot": float(slot_cost.mean()),
            "baseline_total_cost": float(slot_cost.sum()),
        }

    return metrics, cost_stats


def main() -> int:
    engine = _get_engine()
    run = _load_latest_run(engine.db_path)
    if run is None:
        print("[antares-eval] No rows in antares_training_runs; run ml/train_antares.py first.")
        return 1

    print("[antares-eval] Evaluating latest Antares v1 run:")
    print(f"  run_id:           {run.run_id}")
    print(f"  dataset_version:  {run.dataset_version}")
    print(f"  train window:     {run.train_start_date} → {run.train_end_date}")
    print(f"  val window:       {run.val_start_date} → {run.val_end_date}")
    print(f"  artifact_dir:     {run.artifact_dir}")

    metrics, cost_stats = evaluate_run(run)
    if not metrics:
        print("[antares-eval] No metrics computed (no validation data or models).")
        return 1

    print("\n[antares-eval] Per-target imitation quality (validation window):")
    for target, m in metrics.items():
        mae = m["mae"]
        mean_true = abs(m["mean_true"]) or 1e-9
        rel = min(1.0, mae / mean_true) if mean_true > 0 else 0.0
        bar = _ascii_bar(rel)
        print(f"  {target:17s} MAE={mae:0.4f}  mean={mean_true:0.4f}  rel={rel:0.2f}  {bar}")

    if cost_stats:
        print("\n[antares-eval] Validation baseline cost (MPC actions):")
        print(f"  mean cost/slot: {cost_stats['baseline_mean_cost_per_slot']:0.4f} SEK")
        print(f"  total cost:     {cost_stats['baseline_total_cost']:0.2f} SEK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
