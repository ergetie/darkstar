"""
Price model training for Nordpool spot price forecasting.

This module trains LightGBM quantile regression models to predict
Nordpool spot prices for D+1 through D+7 horizons.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.learning.models import SlotObservation


def train_price_model(
    db_path: str = "data/planner_learning.db",
    model_dir: Path = Path("data/ml/models"),
    model_name: str = "price_model.lgb",
    min_training_samples: int = 500,
    recency_half_life_days: float = 30.0,
) -> bool:
    """
    Train LightGBM quantile models for spot price forecasting.

    Queries price_forecasts joined with slot_observations to build training pairs
    using stored weather inputs paired with actual spot prices.

    Args:
        db_path: Path to SQLite database
        model_dir: Directory to save trained models
        model_name: Base filename for the model
        min_training_samples: Minimum samples required to train
        recency_half_life_days: Half-life for exponential decay sample weighting

    Returns:
        True if training succeeded, False otherwise
    """
    print("--- Starting Price Model Training ---")

    # Create model directory if it doesn't exist
    model_dir.mkdir(parents=True, exist_ok=True)

    # Build training dataset by joining price_forecasts with slot_observations
    training_data = _build_training_dataset(db_path)

    if training_data is None or training_data.empty:
        print("No training data available (no price forecasts with matching observations).")
        return False

    n_samples = len(training_data)
    print(f"Found {n_samples} training samples.")

    # Learning-tier gating
    if n_samples < min_training_samples:
        print(
            f"Skipping training: only {n_samples} samples available; "
            f"requires at least {min_training_samples}."
        )
        return False

    # Compute sample weights based on recency
    sample_weights = _compute_sample_weights(training_data, half_life_days=recency_half_life_days)

    # Prepare features and target
    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "is_holiday",
        "days_ahead",
        "price_lag_1d",
        "price_lag_7d",
        "price_lag_24h_avg",
        "wind_index",
        "temperature_c",
        "cloud_cover",
        "radiation_wm2",
    ]

    X = training_data[feature_cols]
    y = training_data["export_price_sek_kwh"].astype(float)

    # Train quantile models
    quantiles = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
    models: dict[str, lgb.LGBMRegressor] = {}

    for q_name, alpha in quantiles.items():
        print(f"  > Training Price {q_name} (alpha={alpha})...")
        model = _train_quantile_regressor(X, y, alpha, sample_weight=sample_weights)
        if model is not None:
            models[q_name] = model
            # Save individual quantile model
            suffix = f"_{q_name}"
            filename = model_name.replace(".lgb", f"{suffix}.lgb")
            _save_model(model, model_dir / filename)

    # Save the p50 model as the main model
    if "p50" in models:
        _save_model(models["p50"], model_dir / model_name)
        print(f"Price model training complete. Saved to {model_dir / model_name}")
        return True
    else:
        print("Warning: Failed to train p50 model.")
        return False


def _build_training_dataset(db_path: str) -> pd.DataFrame | None:
    """
    Build training dataset by joining price_forecasts with slot_observations.

    Returns DataFrame with columns:
    - All feature columns from price_forecasts
    - export_price_sek_kwh (target from slot_observations)
    """
    try:
        # Create SQLAlchemy engine
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        # Query: Join price_forecasts with slot_observations on slot_start
        # Use stored weather inputs from price_forecasts (not actual historical weather)
        query = """
            SELECT
                pf.slot_start,
                pf.issue_timestamp,
                pf.days_ahead,
                pf.wind_index,
                pf.temperature_c,
                pf.cloud_cover,
                pf.radiation_wm2,
                so.export_price_sek_kwh
            FROM price_forecasts pf
            INNER JOIN slot_observations so ON pf.slot_start = so.slot_start
            WHERE so.export_price_sek_kwh IS NOT NULL
            ORDER BY pf.slot_start DESC
        """

        result = session.execute(text(query))
        rows = result.fetchall()

        if not rows:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(
            rows,
            columns=[
                "slot_start",
                "issue_timestamp",
                "days_ahead",
                "wind_index",
                "temperature_c",
                "cloud_cover",
                "radiation_wm2",
                "export_price_sek_kwh",
            ],
        )

        session.close()

        # Parse timestamps
        df["slot_start"] = pd.to_datetime(df["slot_start"], format="ISO8601", utc=True)
        df["issue_timestamp"] = pd.to_datetime(df["issue_timestamp"], format="ISO8601", utc=True)

        # Add calendar features
        df = _add_calendar_features(df)

        # Add price lag features
        df = _add_price_lag_features(df, db_path)

        return df

    except Exception as exc:
        print(f"Error building training dataset: {exc}")
        return None


def _add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add calendar/time features from slot_start timestamp."""
    df = df.copy()
    ts = df["slot_start"]

    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    df["is_holiday"] = df["slot_start"].apply(_is_swedish_holiday).astype(int)

    return df


def _add_price_lag_features(df: pd.DataFrame, db_path: str) -> pd.DataFrame:
    """Add price lag features (1d, 7d, 24h avg) from slot_observations.

    Each lag is masked to NaN unless its source timestamp strictly precedes
    the row's issue_timestamp, so training never sees a value that wouldn't
    have been knowable at forecast issue time.
    """
    df = df.copy()

    # Initialize lag columns with NaN
    df["price_lag_1d"] = np.nan
    df["price_lag_7d"] = np.nan
    df["price_lag_24h_avg"] = np.nan

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        for idx, row in df.iterrows():
            slot_start = row["slot_start"]
            issue_timestamp = row["issue_timestamp"]

            # Price lag 1 day ago — only knowable if its timestamp precedes issue time
            lag_1d = slot_start - timedelta(days=1)
            lag_1d_knowable = lag_1d < issue_timestamp
            if lag_1d_knowable:
                result = (
                    session.query(SlotObservation)
                    .filter(SlotObservation.slot_start == lag_1d.isoformat())
                    .first()
                )
                if result and result.export_price_sek_kwh is not None:
                    df.at[idx, "price_lag_1d"] = result.export_price_sek_kwh

            # Price lag 7 days ago — only knowable if its timestamp precedes issue time
            lag_7d = slot_start - timedelta(days=7)
            if lag_7d < issue_timestamp:
                result = (
                    session.query(SlotObservation)
                    .filter(SlotObservation.slot_start == lag_7d.isoformat())
                    .first()
                )
                if result and result.export_price_sek_kwh is not None:
                    df.at[idx, "price_lag_7d"] = result.export_price_sek_kwh

            # Trailing 24-hour average — whole window masked unless its end (lag_1d) precedes issue time
            if lag_1d_knowable:
                trailing_start = lag_1d - timedelta(hours=23)
                results = (
                    session.query(SlotObservation)
                    .filter(
                        SlotObservation.slot_start >= trailing_start.isoformat(),
                        SlotObservation.slot_start <= lag_1d.isoformat(),
                        SlotObservation.export_price_sek_kwh.isnot(None),
                    )
                    .all()
                )
                if results:
                    prices = [
                        r.export_price_sek_kwh
                        for r in results
                        if r.export_price_sek_kwh is not None
                    ]
                    if prices:
                        df.at[idx, "price_lag_24h_avg"] = sum(prices) / len(prices)

        session.close()

    except Exception as exc:
        print(f"Warning: Error computing price lags: {exc}")

    return df


def _is_swedish_holiday(dt: datetime) -> bool:
    """Check if a date is a Swedish public holiday."""
    month_day = (dt.month, dt.day)

    fixed_holidays = {
        (1, 1),  # New Year's Day
        (1, 6),  # Epiphany
        (5, 1),  # Labour Day
        (6, 6),  # National Day
        (12, 24),  # Christmas Eve
        (12, 25),  # Christmas Day
        (12, 26),  # Boxing Day
        (12, 31),  # New Year's Eve
    }

    if month_day in fixed_holidays:
        return True

    # Midsummer's Eve (Friday between June 19-25)
    if dt.month == 6 and 19 <= dt.day <= 25 and dt.weekday() == 4:
        return True

    # Midsummer's Day (Saturday between June 20-26)
    return dt.month == 6 and 20 <= dt.day <= 26 and dt.weekday() == 5


def _compute_sample_weights(df: pd.DataFrame, half_life_days: float = 30.0) -> np.ndarray:
    """Compute exponential decay weights based on sample age."""
    if df.empty or "slot_start" not in df.columns:
        return np.ones(len(df))

    now = pd.Timestamp.now(tz=df["slot_start"].dt.tz)
    days_ago = (now - df["slot_start"]).dt.total_seconds() / (24 * 3600)

    lambda_param = np.log(2) / half_life_days
    weights = np.exp(-lambda_param * days_ago)

    return weights.values


def _train_quantile_regressor(
    features: pd.DataFrame,
    target: pd.Series,
    alpha: float,
    sample_weight: np.ndarray | None = None,
) -> lgb.LGBMRegressor | None:
    """Train a LightGBM quantile regression model."""
    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=200,
        learning_rate=0.05,
        max_depth=-1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=os.cpu_count() or 1,
        verbosity=-1,
    )

    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None:
        fit_kwargs["sample_weight"] = sample_weight

    model.fit(features, target, **fit_kwargs)  # type: ignore[arg-type]
    return model


def _save_model(model: lgb.LGBMRegressor, path: Path) -> None:
    """Save a LightGBM model to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    booster.save_model(str(path))
    print(f"Saved model to {path}")


if __name__ == "__main__":
    # Allow running as standalone script for testing
    import argparse

    parser = argparse.ArgumentParser(description="Train price forecasting model")
    parser.add_argument(
        "--db-path", default="data/planner_learning.db", help="Path to SQLite database"
    )
    parser.add_argument("--model-dir", default="data/ml/models", help="Directory to save models")
    parser.add_argument("--min-samples", type=int, default=500, help="Minimum training samples")
    parser.add_argument(
        "--half-life-days", type=float, default=30.0, help="Recency half-life in days"
    )

    args = parser.parse_args()

    train_price_model(
        db_path=args.db_path,
        model_dir=Path(args.model_dir),
        min_training_samples=args.min_samples,
        recency_half_life_days=args.half_life_days,
    )
