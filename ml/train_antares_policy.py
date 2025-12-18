from __future__ import annotations

"""
Train a first Antares v1 policy that imitates MPC actions in AntaresMPCEnv.

This is a lightweight, offline-only policy:
  - Uses AntaresMPCEnv to roll out MPC schedules over many days.
  - Collects (state, action) pairs per slot where action is derived from
    the MPC schedule (battery_charge_kw, battery_discharge_kw, export_kwh).
  - Trains one LightGBM regressor per control signal.
  - Saves models under ml/models/antares_policy_v1/ and logs runs in SQLite.
"""

import argparse
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd

from learning import LearningEngine, get_learning_engine
from ml.simulation.env import AntaresMPCEnv


TARGET_NAMES = ["battery_charge_kw", "battery_discharge_kw", "export_kw"]


@dataclass
class PolicyTrainingConfig:
    models_dir: Path = Path("ml/models/antares_policy_v1")
    min_samples: int = 500


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Antares v1 MPC-imitating policy using AntaresMPCEnv.",
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="ml/models/antares_policy_v1",
        help="Directory to store policy models.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=500,
        help="Minimum number of training samples required per target.",
    )
    return parser.parse_args()


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _load_training_days(engine: LearningEngine) -> List[str]:
    """Use data_quality_daily to select clean/mask_battery days."""
    days: List[str] = []
    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            rows = conn.execute(
                """
                SELECT date, status
                FROM data_quality_daily
                WHERE status IN ('clean', 'mask_battery')
                ORDER BY date ASC
                """
            ).fetchall()
    except sqlite3.Error:
        rows = []
    for d, _ in rows:
        days.append(d)
    return days


def _collect_state_action_pairs(days: List[str]) -> pd.DataFrame:
    env = AntaresMPCEnv(config_path="config.yaml")
    records: List[Dict[str, Any]] = []

    for day in days:
        try:
            state = env.reset(day)
        except Exception:
            continue

        schedule = env._schedule  # type: ignore[attr-defined]
        if schedule is None or schedule.empty:
            continue

        for idx, row in schedule.reset_index().iterrows():
            # Rebuild state using env's internal logic for consistency
            state_vec = env._build_state_vector(row)  # type: ignore[attr-defined]

            actions: Dict[str, float] = {}
            charge_kw = float(row.get("battery_charge_kw") or row.get("charge_kw") or 0.0)
            discharge_kw = float(row.get("battery_discharge_kw") or 0.0)
            export_kw = float(row.get("export_kw") or 0.0)

            actions["battery_charge_kw"] = charge_kw
            actions["battery_discharge_kw"] = discharge_kw
            actions["export_kw"] = export_kw

            records.append(
                {
                    "episode_date": day,
                    "slot_index": int(idx),
                    "hour_of_day": float(state_vec[0]),
                    "load_forecast_kwh": float(state_vec[1]),
                    "pv_forecast_kwh": float(state_vec[2]),
                    "projected_soc_percent": float(state_vec[3]),
                    "import_price_sek_kwh": float(state_vec[4]),
                    "export_price_sek_kwh": float(state_vec[5]),
                    **actions,
                }
            )

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


def _train_regressor(
    X: pd.DataFrame,
    y: pd.Series,
    min_samples: int,
) -> Tuple[lgb.LGBMRegressor | None, Dict[str, Any]]:
    if len(X) < min_samples:
        return None, {
            "train_samples": int(len(X)),
            "mae": None,
            "rmse": None,
        }

    model = lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=-1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    model.fit(X, y)

    pred = model.predict(X)
    err = pred - y.to_numpy()
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))

    return model, {
        "train_samples": int(len(X)),
        "mae": mae,
        "rmse": rmse,
    }


def _ensure_policy_runs_table(db_path: str) -> None:
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS antares_policy_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                models_dir TEXT NOT NULL,
                target_names TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _save_policy_models(
    models: Dict[str, lgb.LGBMRegressor],
    base_dir: Path,
    run_id: str,
) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    run_dir = base_dir / f"antares_policy_v1_{timestamp}_{run_id[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for target, model in models.items():
        booster = model.booster_
        fname = f"policy_{target}.lgb"
        path = run_dir / fname
        booster.save_model(str(path))

    return run_dir


def _log_policy_run(
    engine: LearningEngine,
    run_id: str,
    models_dir: Path,
    metrics: Dict[str, Any],
) -> None:
    db_path = engine.db_path
    _ensure_policy_runs_table(db_path)
    row = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat(),
        "models_dir": str(models_dir),
        "target_names": ",".join(TARGET_NAMES),
        "metrics_json": json.dumps(metrics),
    }
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO antares_policy_runs (
                run_id,
                created_at,
                models_dir,
                target_names,
                metrics_json
            ) VALUES (:run_id, :created_at, :models_dir, :target_names, :metrics_json)
            """,
            row,
        )
        conn.commit()


def main() -> int:
    args = _parse_args()
    cfg = PolicyTrainingConfig(
        models_dir=Path(args.models_dir),
        min_samples=args.min_samples,
    )

    engine = _get_engine()
    days = _load_training_days(engine)
    if not days:
        print("[policy-train] No eligible days in data_quality_daily; aborting.")
        return 1

    df = _collect_state_action_pairs(days)
    if df.empty:
        print("[policy-train] No state/action samples collected; aborting.")
        return 1

    feature_cols = [
        "hour_of_day",
        "load_forecast_kwh",
        "pv_forecast_kwh",
        "projected_soc_percent",
        "import_price_sek_kwh",
        "export_price_sek_kwh",
    ]
    for col in feature_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    X = df[feature_cols]
    metrics: Dict[str, Any] = {}
    models: Dict[str, lgb.LGBMRegressor] = {}

    for target in TARGET_NAMES:
        if target not in df.columns:
            metrics[target] = {"train_samples": 0, "mae": None, "rmse": None}
            continue
        y = pd.to_numeric(df[target], errors="coerce").fillna(0.0)
        model, m = _train_regressor(X, y, cfg.min_samples)
        metrics[target] = m
        if model is not None:
            models[target] = model

    if not models:
        print("[policy-train] No models trained; see metrics for details.")
        return 1

    run_id = str(uuid.uuid4())
    run_dir = _save_policy_models(models, cfg.models_dir, run_id)
    _log_policy_run(engine, run_id, run_dir, metrics)

    print("[policy-train] Training completed.")
    print(f"[policy-train] Models saved under: {run_dir}")
    print("[policy-train] Per-target metrics:")
    for target, m in metrics.items():
        print(f"  {target}: {m}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
