from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.learning import LearningEngine, get_learning_engine
from ml.context_features import get_vacation_mode_series
from ml.train import _build_time_features
from ml.weather import get_weather_series


@dataclass
class GraduationLevel:
    level: int
    label: str
    days_of_data: int


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _count_days_with_data(engine: LearningEngine, max_days: int = 90) -> int:
    """
    Count distinct days where both observations and forecasts exist.
    """
    tz = engine.timezone
    cutoff = (datetime.now(tz) - timedelta(days=max_days)).date().isoformat()

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        query = """
            SELECT COUNT(DISTINCT DATE(o.slot_start))
            FROM slot_observations o
            JOIN slot_forecasts f ON o.slot_start = f.slot_start
            WHERE DATE(o.slot_start) >= ?
              AND o.load_kwh IS NOT NULL
              AND f.load_forecast_kwh IS NOT NULL
        """
        row = conn.execute(query, (cutoff,)).fetchone()
        return int(row[0] or 0) if row else 0


def _determine_graduation_level(engine: LearningEngine) -> GraduationLevel:
    days = _count_days_with_data(engine)
    if days < 4:
        return GraduationLevel(level=0, label="infant", days_of_data=days)
    if days < 14:
        return GraduationLevel(level=1, label="statistician", days_of_data=days)
    return GraduationLevel(level=2, label="graduate", days_of_data=days)


def _load_training_frame(engine: LearningEngine, days_back: int = 30) -> pd.DataFrame:
    """
    Build a training dataframe with actuals, base forecasts, and context features.
    """
    tz = engine.timezone
    cutoff_date = (datetime.now(tz) - timedelta(days=days_back)).date().isoformat()

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        query = """
            SELECT
                o.slot_start,
                o.pv_kwh,
                o.load_kwh,
                f.pv_forecast_kwh,
                f.load_forecast_kwh
            FROM slot_observations o
            JOIN slot_forecasts f ON o.slot_start = f.slot_start
            WHERE DATE(o.slot_start) >= ?
              AND o.pv_kwh IS NOT NULL
              AND o.load_kwh IS NOT NULL
              AND f.pv_forecast_kwh IS NOT NULL
              AND f.load_forecast_kwh IS NOT NULL
        """
        df = pd.read_sql_query(query, conn, params=(cutoff_date,))

    if df.empty:
        return df

    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["slot_start"])
    df["slot_start"] = df["slot_start"].dt.tz_convert(tz)

    # Attach weather (temp + cloud) and context flags (vacation)
    start_ts = df["slot_start"].min()
    end_ts = df["slot_start"].max() + timedelta(minutes=15)

    weather_df = get_weather_series(start_ts, end_ts, config=engine.config)
    if not weather_df.empty:
        df = df.merge(weather_df, left_on="slot_start", right_index=True, how="left")
    else:
        df["temp_c"] = np.nan
        df["cloud_cover_pct"] = np.nan

    vac_series = get_vacation_mode_series(
        start_ts - timedelta(days=7), end_ts, config=engine.config
    )
    if not vac_series.empty:
        df = df.merge(
            vac_series.to_frame(name="vacation_mode_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        df["vacation_mode_flag"] = 0.0

    df = _build_time_features(df)

    # Targets: residuals (actual - base)
    df["pv_residual"] = df["pv_kwh"] - df["pv_forecast_kwh"]
    df["load_residual"] = df["load_kwh"] - df["load_forecast_kwh"]

    return df


def _train_error_models(
    df: pd.DataFrame,
    models_dir: str = "ml/models",
) -> dict[str, lgb.Booster]:
    """
    Train LightGBM models to predict residuals for PV and load.
    """
    if df.empty:
        return {}

    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    for col in ("temp_c", "cloud_cover_pct", "vacation_mode_flag"):
        if col in df.columns:
            feature_cols.append(col)

    X = df[feature_cols].fillna(0.0)

    models: dict[str, lgb.Booster] = {}
    for target, model_name in (
        ("pv_residual", "pv_error.lgb"),
        ("load_residual", "load_error.lgb"),
    ):
        if target not in df.columns:
            continue

        y = df[target].astype("float32")
        if y.abs().sum() == 0.0:
            continue

        train_data = lgb.Dataset(X, label=y)
        params = {
            "objective": "regression",
            "metric": "l2",
            "verbosity": -1,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
        }
        booster = lgb.train(params, train_data, num_boost_round=200)
        booster.save_model(f"{models_dir}/{model_name}")
        models[target] = booster

    return models


def train(models_dir: str = "ml/models") -> dict[str, Any]:
    """
    Train or refresh the Aurora Correction models.
    """
    engine = _get_engine()
    level = _determine_graduation_level(engine)
    if level.level < 2:
        # Not enough data for ML yet; rely on stats path.
        return {
            "status": "skipped",
            "reason": f"insufficient data for ML (days={level.days_of_data})",
        }

    df = _load_training_frame(engine)
    if df.empty:
        return {"status": "skipped", "reason": "no training data"}

    models = _train_error_models(df, models_dir=models_dir)
    return {
        "status": "trained",
        "days_of_data": level.days_of_data,
        "models_trained": list(models.keys()),
    }


def _load_error_models(models_dir: str = "ml/models") -> dict[str, lgb.Booster]:
    models: dict[str, lgb.Booster] = {}
    with contextlib.suppress(Exception):
        models["pv_residual"] = lgb.Booster(model_file=f"{models_dir}/pv_error.lgb")
    with contextlib.suppress(Exception):
        models["load_residual"] = lgb.Booster(model_file=f"{models_dir}/load_error.lgb")
    return models


def _compute_stats_bias(
    engine: LearningEngine, days_back: int = 14
) -> dict[tuple[int, int], tuple[float, float]]:
    """
    Compute rolling average residual per (day_of_week, hour) for PV and load.
    """
    tz = engine.timezone
    cutoff_date = (datetime.now(tz) - timedelta(days=days_back)).date().isoformat()

    sql = """
        SELECT
            o.slot_start,
            o.pv_kwh,
            o.load_kwh,
            f.pv_forecast_kwh,
            f.load_forecast_kwh
        FROM slot_observations o
        JOIN slot_forecasts f ON o.slot_start = f.slot_start
        WHERE DATE(o.slot_start) >= ?
          AND o.pv_kwh IS NOT NULL
          AND o.load_kwh IS NOT NULL
          AND f.pv_forecast_kwh IS NOT NULL
          AND f.load_forecast_kwh IS NOT NULL
    """

    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        for slot_start, pv_kwh, load_kwh, pv_forecast, load_forecast in conn.execute(
            sql, (cutoff_date,)
        ):
            try:
                ts = pd.Timestamp(slot_start)
                ts = ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)
                dow = ts.weekday()
                hour = ts.hour
            except Exception:
                continue

            pv_err = float(pv_kwh or 0.0) - float(pv_forecast or 0.0)
            load_err = float(load_kwh or 0.0) - float(load_forecast or 0.0)
            buckets.setdefault((dow, hour), []).append((pv_err, load_err))

    stats: dict[tuple[int, int], tuple[float, float]] = {}
    for key, vals in buckets.items():
        if not vals:
            continue
        pv_vals = [v[0] for v in vals]
        load_vals = [v[1] for v in vals]
        stats[key] = (float(np.mean(pv_vals)), float(np.mean(load_vals)))
    return stats


def _clamp_correction(base: float, raw_correction: float) -> float:
    """
    Clamp corrections to a safe band relative to the base forecast.
    """
    base = float(base or 0.0)
    raw = float(raw_correction or 0.0)
    if base <= 0.0:
        return 0.0
    max_abs = 0.5 * base
    if max_abs <= 0.0:
        return 0.0
    return float(max(-max_abs, min(max_abs, raw)))


def predict_corrections(
    horizon_hours: int = 48,
    forecast_version: str = "aurora",
    models_dir: str = "ml/models",
) -> tuple[list[dict[str, Any]], str]:
    """
    Predict per-slot corrections for the upcoming horizon using the Graduation Path.

    Returns:
        corrections: list of
            {
              "slot_start": datetime,
              "pv_correction_kwh": float,
              "load_correction_kwh": float,
              "correction_source": "none" | "stats" | "ml",
            }
        effective_source: overall dominant source tag.
    """
    engine = _get_engine()
    level = _determine_graduation_level(engine)

    tz = engine.timezone
    now = datetime.now(tz)

    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)

    horizon_end = slot_start + timedelta(hours=horizon_hours)

    # Fetch base forecasts for the horizon window
    from ml.api import get_forecast_slots

    base_records = get_forecast_slots(slot_start, horizon_end, forecast_version)
    if not base_records:
        return [], "none"

    corrections: list[dict[str, Any]] = []

    if level.level == 0:
        # Infant: no corrections at all.
        for rec in base_records:
            corrections.append(
                {
                    "slot_start": rec["slot_start"],
                    "pv_correction_kwh": 0.0,
                    "load_correction_kwh": 0.0,
                    "correction_source": "none",
                }
            )
        return corrections, "none"

    # Level 1+ need statistical bias map
    stats_bias = _compute_stats_bias(engine)

    if level.level == 1:
        # Statistician: rolling average bias only.
        for rec in base_records:
            ts = rec["slot_start"].astimezone(tz)
            key = (ts.weekday(), ts.hour)
            pv_bias, load_bias = stats_bias.get(key, (0.0, 0.0))
            pv_corr = _clamp_correction(rec["pv_forecast_kwh"], pv_bias)
            load_corr = _clamp_correction(rec["load_forecast_kwh"], load_bias)
            corrections.append(
                {
                    "slot_start": rec["slot_start"],
                    "pv_correction_kwh": pv_corr,
                    "load_correction_kwh": load_corr,
                    "correction_source": "stats",
                }
            )
        return corrections, "stats"

    # Level 2: Graduate – ML error model with stats fallback.
    models = _load_error_models(models_dir=models_dir)
    if not models:
        # If ML models are missing, fall back to Level 1 semantics.
        for rec in base_records:
            ts = rec["slot_start"].astimezone(tz)
            key = (ts.weekday(), ts.hour)
            pv_bias, load_bias = stats_bias.get(key, (0.0, 0.0))
            pv_corr = _clamp_correction(rec["pv_forecast_kwh"], pv_bias)
            load_corr = _clamp_correction(rec["load_forecast_kwh"], load_bias)
            corrections.append(
                {
                    "slot_start": rec["slot_start"],
                    "pv_correction_kwh": pv_corr,
                    "load_correction_kwh": load_corr,
                    "correction_source": "stats",
                }
            )
        return corrections, "stats"

    # Build feature frame for the horizon, mirroring forward.py
    df = pd.DataFrame({"slot_start": [rec["slot_start"] for rec in base_records]})

    weather_df = get_weather_series(slot_start, horizon_end, config=engine.config)
    if not weather_df.empty:
        df = df.merge(weather_df, left_on="slot_start", right_index=True, how="left")
    else:
        df["temp_c"] = np.nan
        df["cloud_cover_pct"] = np.nan

    vac_series = get_vacation_mode_series(
        slot_start - timedelta(days=7), horizon_end, config=engine.config
    )
    if not vac_series.empty:
        df = df.merge(
            vac_series.to_frame(name="vacation_mode_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        df["vacation_mode_flag"] = 0.0

    df = _build_time_features(df)

    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    for col in ("temp_c", "cloud_cover_pct", "vacation_mode_flag"):
        if col in df.columns:
            feature_cols.append(col)

    X = df[feature_cols].fillna(0.0)

    for idx, rec in enumerate(base_records):
        ts = rec["slot_start"].astimezone(tz)
        key = (ts.weekday(), ts.hour)
        pv_bias, load_bias = stats_bias.get(key, (0.0, 0.0))

        # Stats fallback values
        stats_pv_corr = _clamp_correction(rec["pv_forecast_kwh"], pv_bias)
        stats_load_corr = _clamp_correction(rec["load_forecast_kwh"], load_bias)

        pv_corr = stats_pv_corr
        load_corr = stats_load_corr
        source = "stats"

        # Attempt ML corrections
        row_features = X.iloc[[idx]]

        if "pv_residual" in models:
            raw_pv = float(models["pv_residual"].predict(row_features)[0])
            ml_pv_corr = _clamp_correction(rec["pv_forecast_kwh"], raw_pv)
            if abs(ml_pv_corr) <= abs(stats_pv_corr) or stats_pv_corr == 0.0:
                pv_corr = ml_pv_corr
                source = "ml"

        if "load_residual" in models:
            raw_load = float(models["load_residual"].predict(row_features)[0])
            ml_load_corr = _clamp_correction(rec["load_forecast_kwh"], raw_load)
            if abs(ml_load_corr) <= abs(stats_load_corr) or stats_load_corr == 0.0:
                load_corr = ml_load_corr
                source = "ml"

        corrections.append(
            {
                "slot_start": rec["slot_start"],
                "pv_correction_kwh": pv_corr,
                "load_correction_kwh": load_corr,
                "correction_source": source,
            }
        )

    return corrections, "ml"
