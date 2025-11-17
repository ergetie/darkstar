from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

import lightgbm as lgb
import pandas as pd
import pytz

from learning import LearningEngine, get_learning_engine


@dataclass
class TrainingConfig:
    days_back: int = 90
    min_samples: int = 500
    models_dir: Path = Path("ml/models")
    load_model_name: str = "load_model.lgb"
    pv_model_name: str = "pv_model.lgb"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train AURORA LightGBM models for load and PV.",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=90,
        help=(
            "Number of days of historical slot_observations to use for training "
            "(default: 90)."
        ),
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=500,
        help="Minimum number of samples required to train each model (default: 500).",
    )
    return parser.parse_args()


def _load_slot_observations(
    engine: LearningEngine,
    start_time: datetime,
    end_time: datetime,
) -> pd.DataFrame:
    """Load slot observations between start_time and end_time."""
    query = """
        SELECT
            slot_start,
            load_kwh,
            pv_kwh
        FROM slot_observations
        WHERE slot_start >= ? AND slot_start < ?
        ORDER BY slot_start ASC
    """
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        df = pd.read_sql_query(
            query,
            conn,
            params=(start_time.isoformat(), end_time.isoformat()),
        )
    if df.empty:
        return df

    # Ensure timezone-aware datetimes
    df["slot_start"] = pd.to_datetime(
        df["slot_start"],
        format="ISO8601",
        utc=True,
        errors="coerce",
    )
    df = df.dropna(subset=["slot_start"])
    df["slot_start"] = df["slot_start"].dt.tz_convert(engine.timezone)

    return df


def _build_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add basic calendar/time features used by both models."""
    ts = df["slot_start"]
    df = df.copy()
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    # Simple cyclical encodings for hour of day
    df["hour_sin"] = (2 * pd.NA)  # placeholders to keep dtypes consistent
    df["hour_cos"] = (2 * pd.NA)
    # Compute sin/cos using float operations
    import numpy as np

    radians = 2 * np.pi * df["hour"] / 24.0
    df["hour_sin"] = np.sin(radians)
    df["hour_cos"] = np.cos(radians)
    return df


def _train_regressor(
    features: pd.DataFrame,
    target: pd.Series,
    min_samples: int,
) -> lgb.LGBMRegressor | None:
    """Train a LightGBM regressor if enough samples are available."""
    if len(features) < min_samples:
        print(
            f"Skipping training: only {len(features)} samples available; "
            f"requires at least {min_samples}.",
        )
        return None

    model = lgb.LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=-1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=os.cpu_count() or 1,
    )

    model.fit(features, target)
    return model


def _save_model(model: lgb.LGBMRegressor, path: Path) -> None:
    """Save a LightGBM model to disk in native format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    booster.save_model(str(path))
    print(f"Saved model to {path}")


def main() -> None:
    args = _parse_args()
    cfg = TrainingConfig(days_back=args.days_back, min_samples=args.min_samples)

    print("--- Starting AURORA Training (Rev 4) ---")

    try:
        engine = get_learning_engine()
        assert isinstance(engine, LearningEngine)
        print(f"Loaded LearningEngine with DB at: {engine.db_path}")
    except Exception as exc:  # pragma: no cover - defensive startup logging
        print(f"Error: Could not initialize LearningEngine. {exc}")
        return

    now = datetime.now(engine.timezone)
    start_time = now - timedelta(days=max(cfg.days_back, 1))

    print(
        "Training window: "
        f"{start_time.isoformat()} to {now.isoformat()} "
        f"({cfg.days_back} days back).",
    )

    observations = _load_slot_observations(engine, start_time, now)
    if observations.empty:
        print("Error: No slot_observations found in the selected time window.")
        return

    # Basic cleaning
    observations = observations.dropna(subset=["slot_start"])
    observations = observations.sort_values("slot_start")

    # Build shared features
    observations = _build_time_features(observations)
    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]

    # Train load model
    load_df = observations.dropna(subset=["load_kwh"])
    load_model_path = cfg.models_dir / cfg.load_model_name
    load_model: lgb.LGBMRegressor | None = None

    if not load_df.empty:
        X_load = load_df[feature_cols]
        y_load = load_df["load_kwh"].astype(float)
        print(f"Training load model on {len(X_load)} samples...")
        load_model = _train_regressor(X_load, y_load, cfg.min_samples)
        if load_model is not None:
            _save_model(load_model, load_model_path)
    else:
        print("Warning: No non-null load_kwh samples found; skipping load model.")

    # Train PV model
    pv_df = observations.dropna(subset=["pv_kwh"])
    pv_model_path = cfg.models_dir / cfg.pv_model_name
    pv_model: lgb.LGBMRegressor | None = None

    if not pv_df.empty:
        X_pv = pv_df[feature_cols]
        y_pv = pv_df["pv_kwh"].astype(float)
        print(f"Training PV model on {len(X_pv)} samples...")
        pv_model = _train_regressor(X_pv, y_pv, cfg.min_samples)
        if pv_model is not None:
            _save_model(pv_model, pv_model_path)
    else:
        print("Warning: No non-null pv_kwh samples found; skipping PV model.")

    if load_model is None and pv_model is None:
        print("No models were trained; check data volume and configuration.")
    else:
        print("--- AURORA Training finished ---")


if __name__ == "__main__":
    main()
