from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytz

from learning import LearningEngine, get_learning_engine
from ml.weather import get_weather_series
from ml.context_features import get_alarm_armed_series, get_vacation_mode_series


@dataclass
class TrainingConfig:
    days_back: int = 90
    # Reduced from 500 to 100 to allow training on small datasets (Cold Start scenario)
    min_samples: int = 100
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
        default=100,
        help="Minimum number of samples required to train each model (default: 100).",
    )
    return parser.parse_args()


def _load_slot_observations(
    engine: LearningEngine,
    start_time: datetime,
    end_time: datetime,
) -> pd.DataFrame:
    """Load slot observations, strictly filtering out zero-artifacts."""
    # We filter load_kwh > 0.001 to exclude rows that were created by
    # store_slot_prices (default 0.0) but never updated with actual sensor data.
    # Real household load is effectively never exactly 0.000.
    query = """
        SELECT
            slot_start,
            load_kwh,
            pv_kwh
        FROM slot_observations
        WHERE slot_start >= ? AND slot_start < ?
          AND load_kwh > 0.001
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

    # Cyclical encodings for hour of day
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

    print("--- Starting AURORA Training (Rev 4+16) ---")

    try:
        engine = get_learning_engine()
        assert isinstance(engine, LearningEngine)
        print(f"Loaded LearningEngine with DB at: {engine.db_path}")
    except Exception as exc:
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
        print("Error: No valid (non-zero load) observations found in window.")
        print("Action: Check if data_activator has run or if sensors are reporting 0.")
        return

    print(f"Loaded {len(observations)} valid observation rows (filtered out zeros).")

    # Basic cleaning
    observations = observations.sort_values("slot_start")

    # Enrich with hourly weather where available
    weather_df = get_weather_series(start_time, now, config=engine.config)
    if not weather_df.empty:
        observations = observations.merge(
            weather_df,
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        observations["temp_c"] = None

    # Ensure numeric dtypes for LightGBM
    for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
        if col in observations.columns:
            observations[col] = pd.to_numeric(observations[col], errors="coerce")

    # Enrich with context flags
    vac_series = get_vacation_mode_series(start_time, now, config=engine.config)
    if not vac_series.empty:
        vac_df = vac_series.to_frame(name="vacation_mode_flag")
        observations = observations.merge(
            vac_df,
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        observations["vacation_mode_flag"] = 0.0

    alarm_series = get_alarm_armed_series(start_time, now, config=engine.config)
    if not alarm_series.empty:
        alarm_df = alarm_series.to_frame(name="alarm_armed_flag")
        observations = observations.merge(
            alarm_df,
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        observations["alarm_armed_flag"] = 0.0

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

    # Dynamically add optional features if they exist
    optional_features = [
        "temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2",
        "vacation_mode_flag", "alarm_armed_flag"
    ]
    for feat in optional_features:
        if feat in observations.columns:
            feature_cols.append(feat)

    # Train load model
    # Filter outliers again just in case (sanity check)
    load_df = observations[observations["load_kwh"] > 0.001].copy()
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
        print("Warning: No valid load_kwh samples found; skipping load model.")

    # Train PV model
    # For PV, we keep 0s because 0 PV is valid (clouds/night), but only if we trust the row.
    # Since we filtered the SQL by load > 0.001, these rows are likely valid observations.
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
        print("No models were trained; check data volume (need >100 valid rows).")
    else:
        print("--- AURORA Training finished ---")


if __name__ == "__main__":
    main()
