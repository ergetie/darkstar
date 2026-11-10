"""
Training script for Aurora (LightGBM-based demand/PV forecasting).

Supports hybrid PV forecasting where ML learns residuals (actual - physics).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.learning import LearningEngine, get_learning_engine
from backend.learning.pv_cleaning import (
    clean_pv_slots,
    site_location,
    total_solar_kwp,
)
from backend.validation import get_max_energy_per_slot
from ml.context_features import get_alarm_armed_series, get_vacation_mode_series
from ml.load_clean import (
    LOAD_SCHEMA_VERSION,
    clean_load_observations,
    empty_clean_stats,
    load_level_7d,
)
from ml.weather import get_historical_weather_series


@dataclass
class TrainingConfig:
    # Reduced from 500 to 100 to allow training on small datasets (Cold Start scenario)
    min_samples: int = 100
    models_dir: Path = Path("data/ml/models")
    load_model_name: str = "load_model.lgb"
    pv_model_name: str = "pv_model.lgb"
    recency_half_life_days: float = 30.0  # Exponential decay half-life for sample weights


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train AURORA LightGBM models for load and PV.",
    )
    parser.add_argument(
        "--recency-half-life-days",
        type=float,
        default=30.0,
        help="Half-life for exponential decay sample weighting (default: 30.0 days).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=100,
        help="Minimum number of samples required to train each model (default: 100).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete all existing models in ml/models before training.",
    )
    return parser.parse_args()


def delete_trained_models(models_dir: Path = Path("data/ml/models")) -> None:
    """Delete all .lgb files in the models directory."""
    if not models_dir.exists():
        return
    for f in models_dir.glob("*.lgb"):
        f.unlink()
        print(f"Deleted model: {f}")


def _compute_sample_weights(
    df: pd.DataFrame,
    half_life_days: float = 30.0,
    config: TrainingConfig | None = None,
) -> np.ndarray:
    """Compute exponential decay weights based on sample age.

    Weight = exp(-lambda * days_ago) where lambda = ln(2) / half_life_days

    Args:
        df: DataFrame with 'slot_start' column containing timestamps
        half_life_days: Number of days for weight to decay to 0.5 (default: 30)
        config: Optional TrainingConfig (can override half_life_days via config)

    Returns:
        Array of weights corresponding to each row in df
    """
    # Allow config override
    if config is not None:
        half_life_days = getattr(config, "recency_half_life_days", half_life_days)

    if df.empty or "slot_start" not in df.columns:
        return np.ones(len(df))

    now = pd.Timestamp.now(tz=df["slot_start"].dt.tz)
    days_ago = (now - df["slot_start"]).dt.total_seconds() / (24 * 3600)

    # Exponential decay: weight = exp(-lambda * days_ago)
    # At half_life_days, weight = 0.5, so lambda = ln(2) / half_life_days
    lambda_param = np.log(2) / half_life_days
    weights = np.exp(-lambda_param * days_ago)

    return weights.values


def _load_slot_observations(  # type: ignore[reportUnusedFunction]
    engine: LearningEngine,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> pd.DataFrame:
    """Load slot observations, strictly filtering out zero-artifacts and sensor spikes.

    Thin wrapper over ``_load_raw_slot_observations`` that drops near-zero load rows
    (``load_kwh > 0.001``). Use ``load_clean_load_observations`` for load training and
    load inference, which also applies the load data-quality rules.
    """
    df = _load_raw_slot_observations(engine, start_time, end_time)
    if df.empty:
        return df
    return df[df["load_kwh"] > 0.001].reset_index(drop=True)


def load_clean_load_observations(
    engine: LearningEngine,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Observations cleaned for load use (backfill and clamp-day rules, then load > 0.001)."""
    raw = _load_raw_slot_observations(engine, start_time, end_time)
    if raw.empty:
        return raw, empty_clean_stats()
    clean, stats = clean_load_observations(raw)
    return clean[clean["load_kwh"] > 0.001].reset_index(drop=True), stats


def _load_raw_slot_observations(
    engine: LearningEngine,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> pd.DataFrame:
    """Load slot observations incl. near-zero load rows, filtering sensor spikes.

    Near-zero (but non-negative) load rows are kept because the clamp-day detector in
    ``ml/load_clean.py`` needs them; callers apply ``load_kwh > 0.001`` afterwards.

    If start_time is None, loads all available data from the earliest record.
    If end_time is None, loads up to the current time.

    Rows whose quality_flags JSON contains "exclude": true (set out-of-band by
    scripts/flag_january_bad_slots.py, e.g. for the January 2026 corruption
    cluster) are excluded from every branch below — see backend/learning/store.py
    for how the flag is preserved alongside "source".
    """
    max_kwh = get_max_energy_per_slot(engine.config)

    # Build query based on provided time range
    if start_time is None and end_time is None:
        # Load all available data
        query = """
            SELECT
                o.slot_start,
                o.load_kwh,
                o.pv_kwh,
                o.soc_end_percent,
                o.export_kwh,
                o.import_kwh,
                o.batt_discharge_kwh,
                o.quality_flags,
                f.openmeteo_pv_forecast_kwh
            FROM slot_observations o
            LEFT JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
             AND f.forecast_version = 'aurora'
            WHERE o.load_kwh >= 0
              AND o.load_kwh <= ?
              AND o.pv_kwh <= ?
              AND (o.quality_flags IS NULL OR o.quality_flags NOT LIKE '%"exclude": true%')
            ORDER BY o.slot_start ASC
        """
        params = (max_kwh, max_kwh)
    elif start_time is None:
        # Load from beginning up to end_time
        assert end_time is not None, "end_time must not be None when start_time is None"
        query = """
            SELECT
                o.slot_start,
                o.load_kwh,
                o.pv_kwh,
                o.soc_end_percent,
                o.export_kwh,
                o.import_kwh,
                o.batt_discharge_kwh,
                o.quality_flags,
                f.openmeteo_pv_forecast_kwh
            FROM slot_observations o
            LEFT JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
             AND f.forecast_version = 'aurora'
            WHERE o.slot_start < ?
              AND o.load_kwh >= 0
              AND o.load_kwh <= ?
              AND o.pv_kwh <= ?
              AND (o.quality_flags IS NULL OR o.quality_flags NOT LIKE '%"exclude": true%')
            ORDER BY o.slot_start ASC
        """
        params = (end_time.isoformat(), max_kwh, max_kwh)
    elif end_time is None:
        # Load from start_time to now
        now = datetime.now(engine.timezone)
        query = """
            SELECT
                o.slot_start,
                o.load_kwh,
                o.pv_kwh,
                o.soc_end_percent,
                o.export_kwh,
                o.import_kwh,
                o.batt_discharge_kwh,
                o.quality_flags,
                f.openmeteo_pv_forecast_kwh
            FROM slot_observations o
            LEFT JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
             AND f.forecast_version = 'aurora'
            WHERE o.slot_start >= ?
              AND o.slot_start < ?
              AND o.load_kwh >= 0
              AND o.load_kwh <= ?
              AND o.pv_kwh <= ?
              AND (o.quality_flags IS NULL OR o.quality_flags NOT LIKE '%"exclude": true%')
            ORDER BY o.slot_start ASC
        """
        params = (start_time.isoformat(), now.isoformat(), max_kwh, max_kwh)
    else:
        # Both start and end provided
        query = """
            SELECT
                o.slot_start,
                o.load_kwh,
                o.pv_kwh,
                o.soc_end_percent,
                o.export_kwh,
                o.import_kwh,
                o.batt_discharge_kwh,
                o.quality_flags,
                f.openmeteo_pv_forecast_kwh
            FROM slot_observations o
            LEFT JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
             AND f.forecast_version = 'aurora'
            WHERE o.slot_start >= ?
              AND o.slot_start < ?
              AND o.load_kwh >= 0
              AND o.load_kwh <= ?
              AND o.pv_kwh <= ?
              AND (o.quality_flags IS NULL OR o.quality_flags NOT LIKE '%"exclude": true%')
            ORDER BY o.slot_start ASC
        """
        params = (start_time.isoformat(), end_time.isoformat(), max_kwh, max_kwh)

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        has_slot_forecasts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'slot_forecasts'"
        ).fetchone()
        if has_slot_forecasts is None:
            conn.execute(
                """
                CREATE TEMP TABLE slot_forecasts (
                    slot_start TEXT,
                    forecast_version TEXT,
                    openmeteo_pv_forecast_kwh REAL
                )
                """
            )
        df = pd.read_sql_query(
            query,
            conn,
            params=params,
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
    df = df.reset_index(drop=True)

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
    alpha: float = 0.5,
    sample_weight: np.ndarray | None = None,
) -> lgb.LGBMRegressor | None:
    """Train a LightGBM regressor (Quantile Regression) if enough samples are available."""
    if len(features) < min_samples:
        print(
            f"Skipping training: only {len(features)} samples available; "
            f"requires at least {min_samples}.",
        )
        return None

    # Use quantile objective
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

    # Pass sample weights to fit() if provided
    fit_kwargs: dict[str, Any] = {}
    if sample_weight is not None:
        fit_kwargs["sample_weight"] = sample_weight

    model.fit(features, target, **fit_kwargs)  # type: ignore[reportUnknownMemberType]
    return model


def _save_model(
    model: lgb.LGBMRegressor,
    path: Path,
    feature_names: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Save a LightGBM model to disk in native format."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    booster = model.booster_
    booster.save_model(str(path))
    if feature_names is not None:
        path.with_suffix(".features.json").write_text(
            json.dumps({"feature_names": feature_names, **(extra or {})})
        )
    print(f"Saved model to {path}")


def train_models(min_samples: int = 100, recency_half_life_days: float = 30.0) -> None:
    cfg = TrainingConfig(min_samples=min_samples, recency_half_life_days=recency_half_life_days)

    print("--- Starting AURORA Training (Rev K16: Hybrid PV with Physics Residuals) ---")

    try:
        engine = get_learning_engine()
        assert isinstance(engine, LearningEngine)
        print(f"Loaded LearningEngine with DB at: {engine.db_path}")
    except Exception as exc:
        print(f"Error: Could not initialize LearningEngine. {exc}")
        return

    now = datetime.now(engine.timezone)

    try:
        from backend.learning.pv_openmeteo_backfill import backfill_openmeteo_pv_baselines

        backfilled = asyncio.run(backfill_openmeteo_pv_baselines(engine, days=28))
        if backfilled > 0:
            print(
                f"Backfilled {backfilled} missing Open-Meteo PV baseline slots for residual training."
            )
    except RuntimeError as exc:
        print(f"Warning: Skipped Open-Meteo PV backfill: {exc}")

    print(
        "Training window: loading all available historical data "
        f"with recency weighting (half-life={cfg.recency_half_life_days} days).",
    )

    raw_observations = _load_raw_slot_observations(engine, end_time=now)
    # Load data rule (backfill rows, clamp-signature days) needs the near-zero rows, so it
    # runs on the raw frame; the load_kwh > 0.001 filter is applied afterwards.
    if raw_observations.empty:
        load_clean_index: pd.Index = raw_observations.index
        load_clean_stats = empty_clean_stats()
    else:
        clean_raw, load_clean_stats = clean_load_observations(raw_observations)
        load_clean_index = clean_raw.index
    observations = raw_observations[raw_observations["load_kwh"] > 0.001].copy()
    observations["load_clean"] = observations.index.isin(load_clean_index)
    observations = observations.reset_index(drop=True)
    print(
        "Load data rule dropped "
        f"{load_clean_stats['dropped_backfill_rows']} backfill rows and "
        f"{load_clean_stats['dropped_clamp_days']} clamp-signature days "
        f"({load_clean_stats['dropped_clamp_rows']} rows)."
    )
    if observations.empty:
        print("Error: No valid (non-zero load) observations found.")
        print("Action: Check if the recorder has run or if sensors are reporting 0.")
        return

    # Get time range from observations for feature enrichment
    obs_start = observations["slot_start"].min()
    obs_end = observations["slot_start"].max()
    print(f"Loaded {len(observations)} valid observation rows from {obs_start} to {obs_end}.")

    # Basic cleaning
    observations = observations.sort_values("slot_start")

    # Compute sample weights based on recency; wrap in a Series indexed by observations.index
    # so that label-safe .loc slicing works even if the index was reset
    sample_weights = pd.Series(
        _compute_sample_weights(observations, config=cfg),
        index=observations.index,
    )

    # Enrich with real historical weather (inference uses forecast weather, same columns)
    weather_df = get_historical_weather_series(obs_start, now, config=engine.config)
    if not weather_df.empty:
        observations = observations.merge(
            weather_df,
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        print(
            "Warning: Historical weather unavailable; training continues without weather features."
        )
        for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
            observations[col] = np.nan

    # Ensure numeric dtypes for LightGBM
    for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
        if col in observations.columns:
            observations[col] = pd.to_numeric(observations[col], errors="coerce")

    # Enrich with context flags
    vac_series = get_vacation_mode_series(obs_start, now, config=engine.config)
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

    alarm_series = get_alarm_armed_series(obs_start, now, config=engine.config)
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
        "temp_c",
        "cloud_cover_pct",
        "shortwave_radiation_w_m2",
        "vacation_mode_flag",
        "alarm_armed_flag",
    ]
    for feat in optional_features:
        if feat in observations.columns:
            feature_cols.append(feat)

    # Quantiles to train
    quantiles = {"p10": 0.1, "p50": 0.5, "p90": 0.9}
    load_sidecar_extra: dict[str, Any] = {
        "schema_version": LOAD_SCHEMA_VERSION,
        "training_stats": load_clean_stats,
    }

    # --- Train Load Models ---
    load_df = observations[observations["load_clean"] & (observations["load_kwh"] > 0.001)].copy()
    load_feature_cols = [*feature_cols, "load_level_7d"]
    if not load_df.empty:
        # Level of the previous clean days, strictly before each slot's local day.
        load_df["load_level_7d"] = load_level_7d(load_df, load_df["slot_start"])
        X_load = load_df[load_feature_cols]
        y_load = load_df["load_kwh"].astype(float)
        # Extract sample weights for load training samples (label-safe .loc)
        load_weights = sample_weights.loc[load_df.index].to_numpy()
        print(f"Training load models on {len(X_load)} samples...")

        for q_name, alpha in quantiles.items():
            print(f"  > Training Load {q_name} (alpha={alpha})...")
            model = _train_regressor(
                X_load, y_load, cfg.min_samples, alpha=alpha, sample_weight=load_weights
            )
            if model is not None:
                suffix = f"_{q_name}"
                filename = cfg.load_model_name.replace(".lgb", f"{suffix}.lgb")
                _save_model(
                    model,
                    cfg.models_dir / filename,
                    feature_names=load_feature_cols,
                    extra=load_sidecar_extra,
                )

                if q_name == "p50":
                    _save_model(
                        model,
                        cfg.models_dir / cfg.load_model_name,
                        feature_names=load_feature_cols,
                        extra=load_sidecar_extra,
                    )
    else:
        print("Warning: No valid load_kwh samples found; skipping load models.")

    # --- Train PV Models ---
    # HYBRID PV: Train on residuals (actual - Open-Meteo baseline)
    pv_df = observations.dropna(subset=["pv_kwh"]).copy()

    if not pv_df.empty:
        # Shared cleaning (also feeds the Reflex bias): keeps shaded zero slots, drops night,
        # dropouts, spikes and curtailed slots (and slots without a baseline).
        latitude, longitude = site_location(engine.config)
        before = len(pv_df)
        cleaned = clean_pv_slots(
            pv_df.rename(columns={"openmeteo_pv_forecast_kwh": "baseline_kwh"}),
            total_kwp=total_solar_kwp(engine.config),
            latitude=latitude,
            longitude=longitude,
        )
        dropped_by_rule = cleaned.attrs.get("dropped_by_rule", {})
        pv_df = cleaned.rename(columns={"baseline_kwh": "openmeteo_pv_forecast_kwh"})
        print(
            f"PV cleaning dropped {before - len(pv_df)} of {before} slots "
            f"(by rule: {', '.join(f'{k}={v}' for k, v in dropped_by_rule.items())})"
        )
        if pv_df.empty:
            print("Warning: No stored Open-Meteo baselines found; skipping PV models.")
        else:
            pv_df["openmeteo_pv_forecast_kwh"] = pv_df["openmeteo_pv_forecast_kwh"].astype(float)
            pv_df["pv_residual"] = pv_df["pv_kwh"] - pv_df["openmeteo_pv_forecast_kwh"]
            pv_df["physics_forecast_kwh"] = pv_df["openmeteo_pv_forecast_kwh"]

            print(
                f"PV Residual Stats: mean={pv_df['pv_residual'].mean():.4f}, "
                f"std={pv_df['pv_residual'].std():.4f}, "
                f"min={pv_df['pv_residual'].min():.4f}, max={pv_df['pv_residual'].max():.4f}"
            )

            # Feature columns for PV (add baseline forecast)
            pv_feature_cols = feature_cols.copy()
            if (
                "physics_forecast_kwh" in pv_df.columns
                and "physics_forecast_kwh" not in pv_feature_cols
            ):
                pv_feature_cols.append("physics_forecast_kwh")

            X_pv = pv_df[pv_feature_cols]
            y_pv = pv_df["pv_residual"].astype(float)
            # Extract sample weights for PV training samples (label-safe .loc)
            pv_weights = sample_weights.loc[pv_df.index].to_numpy()
            print(f"Training PV models on {len(X_pv)} samples (residual mode)...")

            for q_name, alpha in quantiles.items():
                print(f"  > Training PV {q_name} (alpha={alpha})...")
                model = _train_regressor(
                    X_pv, y_pv, cfg.min_samples, alpha=alpha, sample_weight=pv_weights
                )
                if model is not None:
                    suffix = f"_{q_name}"
                    filename = cfg.pv_model_name.replace(".lgb", f"{suffix}.lgb")
                    _save_model(model, cfg.models_dir / filename, feature_names=pv_feature_cols)

                    if q_name == "p50":
                        _save_model(
                            model, cfg.models_dir / cfg.pv_model_name, feature_names=pv_feature_cols
                        )
    else:
        print("Warning: No non-null pv_kwh samples found; skipping PV models.")

    print("--- AURORA Training finished ---")

    # Log run to DB
    try:
        import json

        run_metrics = {
            "load_models_trained": not load_df.empty,
            "pv_models_trained": not pv_df.empty,
            "load_schema_version": LOAD_SCHEMA_VERSION,
            **load_clean_stats,
        }
        run_params = {
            "recency_half_life_days": cfg.recency_half_life_days,
            "min_samples": cfg.min_samples,
        }

        with sqlite3.connect(engine.db_path) as conn:
            conn.execute(
                """
                INSERT INTO learning_runs
                (started_at, completed_at, status, params_json, result_metrics_json, training_type, partial_failure)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    datetime.now(engine.timezone).isoformat(),
                    "success",
                    json.dumps(run_params),
                    json.dumps(run_metrics),
                    "automatic",
                    0,
                ),
            )
            conn.commit()
            print("Logged learning run to DB.")
    except Exception as e:
        print(f"Failed to log learning run: {e}")


if __name__ == "__main__":
    args = _parse_args()
    if args.clear:
        delete_trained_models()
    train_models(
        min_samples=args.min_samples,
        recency_half_life_days=args.recency_half_life_days,
    )
