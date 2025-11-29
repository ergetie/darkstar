from __future__ import annotations

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
from ml.api import get_antares_slots
from ml.train import _build_time_features


TARGET_COLUMNS = ["batt_charge_kwh", "batt_discharge_kwh", "export_kwh"]


@dataclass
class TrainingConfig:
    dataset_version: str = "v1"
    min_samples: int = 200
    models_dir: Path = Path("ml/models/antares_v1")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Antares v1 LightGBM models on simulation episodes.",
    )
    parser.add_argument(
        "--dataset-version",
        type=str,
        default="v1",
        help="Antares dataset version to use (default: v1).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=200,
        help="Minimum number of training samples per target (default: 200).",
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="ml/models/antares_v1",
        help="Directory to store trained Antares v1 models.",
    )
    return parser.parse_args()


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _ensure_training_runs_table(db_path: str) -> None:
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS antares_training_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                train_start_date TEXT NOT NULL,
                train_end_date TEXT NOT NULL,
                val_start_date TEXT,
                val_end_date TEXT,
                targets TEXT NOT NULL,
                model_type TEXT NOT NULL,
                hyperparams_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                artifact_dir TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _build_feature_frame(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    data = df.copy()
    data["slot_start"] = pd.to_datetime(
        data["slot_start"],
        utc=True,
        errors="coerce",
    )
    data = data.dropna(subset=["slot_start"])
    data["episode_date_dt"] = pd.to_datetime(data["episode_date"]).dt.date

    data = _build_time_features(data)

    feature_cols: List[str] = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]

    numeric_cols = [
        "import_price_sek_kwh",
        "export_price_sek_kwh",
        "load_kwh",
        "pv_kwh",
        "import_kwh",
        "soc_start_percent",
        "soc_end_percent",
        "battery_masked",
    ]
    for col in numeric_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
            feature_cols.append(col)

    return data, feature_cols


def _split_train_val(data: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(data["episode_date_dt"].unique())
    if not dates:
        return data.iloc[0:0].copy(), data.iloc[0:0].copy()

    if len(dates) == 1:
        train_dates = set(dates)
        val_dates: set = set()
    else:
        split_index = int(len(dates) * 0.8)
        if split_index <= 0:
            split_index = 1
        train_dates = set(dates[:split_index])
        val_dates = set(dates[split_index:])

    data = data.copy()
    data["is_train"] = data["episode_date_dt"].isin(train_dates)
    train_df = data[data["is_train"]].copy()
    val_df = data[~data["is_train"]].copy()
    return train_df, val_df


def _train_target_model(
    target: str,
    full_data: pd.DataFrame,
    feature_cols: List[str],
    min_samples: int,
) -> Tuple[lgb.LGBMRegressor | None, Dict[str, Any]]:
    data = full_data.copy()
    if target in ("batt_charge_kwh", "batt_discharge_kwh"):
        if "battery_masked" in data.columns:
            data = data[~data["battery_masked"].astype(bool)]

    data = data[data[target].notnull()]
    if data.empty:
        return None, {
            "train_samples": 0,
            "val_samples": 0,
            "mae": None,
            "rmse": None,
        }

    dates = sorted(data["episode_date_dt"].unique())
    if len(dates) == 1:
        train_dates = set(dates)
        val_dates: set = set()
    else:
        split_index = int(len(dates) * 0.8)
        if split_index <= 0:
            split_index = 1
        train_dates = set(dates[:split_index])
        val_dates = set(dates[split_index:])

    train_subset = data[data["episode_date_dt"].isin(train_dates)].copy()
    val_subset = data[data["episode_date_dt"].isin(val_dates)].copy()

    X_train = train_subset[feature_cols]
    y_train = train_subset[target].astype(float)

    X_train = X_train.apply(pd.to_numeric, errors="coerce")
    y_train = y_train.where(~y_train.isna(), None)
    X_train = X_train[~y_train.isna()]
    y_train = y_train[~y_train.isna()]

    if len(X_train) < min_samples:
        return None, {
            "train_samples": int(len(X_train)),
            "val_samples": int(len(val_subset)),
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
    model.fit(X_train, y_train)

    if val_subset.empty:
        mae = None
        rmse = None
    else:
        X_val = val_subset[feature_cols]
        y_val = val_subset[target].astype(float)
        X_val = X_val.apply(pd.to_numeric, errors="coerce")
        mask_val = ~y_val.isna()
        X_val = X_val[mask_val]
        y_val = y_val[mask_val]
        if len(X_val) == 0:
            mae = None
            rmse = None
        else:
            pred = model.predict(X_val)
            err = pred - y_val.to_numpy()
            mae = float(np.mean(np.abs(err)))
            rmse = float(np.sqrt(np.mean(err**2)))

    metrics: Dict[str, Any] = {
        "train_samples": int(len(X_train)),
        "val_samples": int(len(val_subset)),
        "mae": mae,
        "rmse": rmse,
    }
    return model, metrics


def _save_models(
    models: Dict[str, lgb.LGBMRegressor],
    base_dir: Path,
    run_id: str,
) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    run_dir = base_dir / f"antares_v1_{timestamp}_{run_id[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    for target, model in models.items():
        booster = model.booster_
        path = run_dir / f"{target}.lgb"
        booster.save_model(str(path))

    return run_dir


def _log_training_run(
    db_path: str,
    run_id: str,
    cfg: TrainingConfig,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    metrics: Dict[str, Any],
    artifact_dir: Path,
) -> None:
    train_dates = sorted(train_df["episode_date_dt"].unique())
    val_dates = sorted(val_df["episode_date_dt"].unique())

    train_start = train_dates[0].isoformat() if train_dates else ""
    train_end = train_dates[-1].isoformat() if train_dates else ""
    val_start = val_dates[0].isoformat() if val_dates else None
    val_end = val_dates[-1].isoformat() if val_dates else None

    row = {
        "run_id": run_id,
        "created_at": datetime.utcnow().isoformat(),
        "dataset_version": cfg.dataset_version,
        "train_start_date": train_start,
        "train_end_date": train_end,
        "val_start_date": val_start,
        "val_end_date": val_end,
        "targets": ",".join(TARGET_COLUMNS),
        "model_type": "lightgbm_regressor",
        "hyperparams_json": json.dumps(
            {
                "n_estimators": 200,
                "learning_rate": 0.05,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "random_state": 42,
            }
        ),
        "metrics_json": json.dumps(metrics),
        "artifact_dir": str(artifact_dir),
    }

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO antares_training_runs (
                run_id,
                created_at,
                dataset_version,
                train_start_date,
                train_end_date,
                val_start_date,
                val_end_date,
                targets,
                model_type,
                hyperparams_json,
                metrics_json,
                artifact_dir
            ) VALUES (:run_id, :created_at, :dataset_version, :train_start_date,
                      :train_end_date, :val_start_date, :val_end_date, :targets,
                      :model_type, :hyperparams_json, :metrics_json, :artifact_dir)
            """,
            row,
        )
        conn.commit()


def main() -> int:
    args = _parse_args()
    cfg = TrainingConfig(
        dataset_version=args.dataset_version,
        min_samples=args.min_samples,
        models_dir=Path(args.models_dir),
    )

    engine = _get_engine()
    db_path = engine.db_path
    _ensure_training_runs_table(db_path)

    df = get_antares_slots(dataset_version=cfg.dataset_version)
    if df.empty:
        print("[antares] dataset is empty; nothing to train.")
        return 1

    data, feature_cols = _build_feature_frame(df)
    train_df, val_df = _split_train_val(data)

    if train_df.empty:
        print("[antares] no training data after split; aborting.")
        return 1

    run_id = str(uuid.uuid4())
    models: Dict[str, lgb.LGBMRegressor] = {}
    target_metrics: Dict[str, Any] = {}

    for target in TARGET_COLUMNS:
        if target not in data.columns:
            target_metrics[target] = {
                "train_samples": 0,
                "val_samples": 0,
                "mae": None,
                "rmse": None,
            }
            continue

        model, metrics = _train_target_model(
            target,
            data,
            feature_cols,
            cfg.min_samples,
        )
        target_metrics[target] = metrics
        if model is not None:
            models[target] = model

    if not models:
        print("[antares] no models trained (insufficient data for all targets).")
        return 1

    artifact_dir = _save_models(models, cfg.models_dir, run_id)

    baseline_cost_stats: Dict[str, Any] = {}
    if not val_df.empty:
        if {"import_kwh", "export_kwh", "import_price_sek_kwh", "export_price_sek_kwh"}.issubset(
            val_df.columns
        ):
            import_cost = (
                val_df["import_kwh"].astype(float)
                * val_df["import_price_sek_kwh"].astype(float)
            )
            export_revenue = (
                val_df["export_kwh"].astype(float)
                * val_df["export_price_sek_kwh"].astype(float)
            )
            slot_cost = import_cost - export_revenue
            baseline_cost_stats = {
                "baseline_mean_cost_per_slot": float(slot_cost.mean()),
                "baseline_total_cost": float(slot_cost.sum()),
            }

    metrics = {
        "targets": target_metrics,
        "validation_baseline_cost": baseline_cost_stats,
    }

    _log_training_run(db_path, run_id, cfg, train_df, val_df, metrics, artifact_dir)

    print("[antares] training completed.")
    print(f"[antares] models saved under: {artifact_dir}")
    print("[antares] per-target metrics:")
    for target, m in target_metrics.items():
        print(f"  {target}: {m}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
