from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytz
import sqlite3

from learning import LearningEngine, get_learning_engine
from ml.train import _build_time_features, _load_slot_observations
from ml.weather import get_weather_series
from ml.context_features import get_vacation_mode_series, get_alarm_armed_series


AURORA_VERSION = "aurora"
BASELINE_VERSION = "baseline_7_day_avg"


@dataclass
class EvaluationConfig:
    days_back: int = 7
    aurora_version: str = AURORA_VERSION
    baseline_version: str = BASELINE_VERSION
    models_dir: Path = Path("ml/models")
    load_model_name: str = "load_model.lgb"
    pv_model_name: str = "pv_model.lgb"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate AURORA forecasts in shadow mode against baseline and actuals.",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Number of days to evaluate over (default: 7).",
    )
    parser.add_argument(
        "--aurora-version",
        type=str,
        default=AURORA_VERSION,
        help="forecast_version name for AURORA forecasts (default: aurora).",
    )
    parser.add_argument(
        "--baseline-version",
        type=str,
        default=BASELINE_VERSION,
        help="forecast_version name for baseline forecasts (default: baseline_7_day_avg).",
    )
    return parser.parse_args()


def _load_model(path: Path) -> lgb.Booster | None:
    if not path.exists():
        print(f"Warning: Model file not found: {path}")
        return None
    booster = lgb.Booster(model_file=str(path))
    print(f"Loaded model from {path}")
    return booster


def _generate_baseline_forecasts(
    observations: pd.DataFrame,
    engine: LearningEngine,
) -> List[Dict]:
    """Simple baseline: 7-day average by hour-of-day for load and PV."""
    if observations.empty:
        return []

    df = observations.copy()
    df["slot_start"] = pd.to_datetime(df["slot_start"])
    if df["slot_start"].dt.tz is None:
        df["slot_start"] = df["slot_start"].dt.tz_localize(engine.timezone)
    else:
        df["slot_start"] = df["slot_start"].dt.tz_convert(engine.timezone)

    df["hour"] = df["slot_start"].dt.hour

    # Use a 7-day window prior to the evaluation horizon for averaging
    end_time = df["slot_start"].max()
    start_time = end_time - timedelta(days=7)
    history = df[(df["slot_start"] >= start_time) & (df["slot_start"] < end_time)]
    if history.empty:
        print("Warning: No history available for baseline computation.")
        return []

    grouped = history.groupby("hour").agg(
        load_kwh=("load_kwh", "mean"),
        pv_kwh=("pv_kwh", "mean"),
        temp_c=("temp_c", "mean") if "temp_c" in history.columns else ("load_kwh", "mean"),
    )

    forecasts: List[Dict] = []
    for _, row in df.iterrows():
        hour = int(row["hour"])
        slot_start_dt = row["slot_start"].astimezone(engine.timezone)
        slot_start = slot_start_dt.isoformat()
        if hour in grouped.index:
            load_forecast = float(grouped.loc[hour, "load_kwh"] or 0.0)
            pv_forecast = float(grouped.loc[hour, "pv_kwh"] or 0.0)
            temp_c = (
                None
                if "temp_c" not in grouped.columns
                else float(grouped.loc[hour, "temp_c"])
            )
        else:
            load_forecast = 0.0
            pv_forecast = 0.0
            temp_c = None

        forecasts.append(
            {
                "slot_start": slot_start,
                "load_forecast_kwh": load_forecast,
                "pv_forecast_kwh": pv_forecast,
                "temp_c": temp_c,
            },
        )
    return forecasts


def _predict_with_boosters(
    boosters: Dict[str, lgb.Booster],
    features: pd.DataFrame,
    observations: pd.DataFrame,
    engine: LearningEngine,
    aurora_version: str,
) -> List[Dict]:
    """Generate AURORA forecasts given boosters and features."""
    if features.empty or observations.empty:
        return []

    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    if "temp_c" in features.columns:
        feature_cols.append("temp_c")
    if "cloud_cover_pct" in features.columns:
        feature_cols.append("cloud_cover_pct")
    if "shortwave_radiation_w_m2" in features.columns:
        feature_cols.append("shortwave_radiation_w_m2")
    if "vacation_mode_flag" in features.columns:
        feature_cols.append("vacation_mode_flag")
    if "alarm_armed_flag" in features.columns:
        feature_cols.append("alarm_armed_flag")

    for col in feature_cols:
        if col in features.columns:
            features[col] = pd.to_numeric(features[col], errors="coerce")

    X = features[feature_cols]

    load_pred = None
    pv_pred = None

    if boosters.get("load") is not None:
        load_pred = boosters["load"].predict(X)
    if boosters.get("pv") is not None:
        pv_pred = boosters["pv"].predict(X)

    forecasts: List[Dict] = []
    for idx, row in observations.iterrows():
        slot_start = pd.to_datetime(row["slot_start"])
        if slot_start.tzinfo is None:
            slot_start = engine.timezone.localize(slot_start)
        else:
            slot_start = slot_start.astimezone(engine.timezone)

        record: Dict = {
            "slot_start": slot_start.isoformat(),
            "pv_forecast_kwh": 0.0,
            "load_forecast_kwh": 0.0,
            "temp_c": row.get("temp_c"),
        }

        pos = features.index.get_loc(idx)
        if load_pred is not None:
            record["load_forecast_kwh"] = float(max(load_pred[pos], 0.0))
        if pv_pred is not None:
            record["pv_forecast_kwh"] = float(max(pv_pred[pos], 0.0))

        forecasts.append(record)
    return forecasts


def _calculate_mae(
    engine: LearningEngine,
    start_time: datetime,
    end_time: datetime,
    forecast_version: str,
) -> Tuple[float | None, float | None]:
    """Calculate MAE for PV and load for a given forecast_version."""
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT
                o.pv_kwh,
                o.load_kwh,
                f.pv_forecast_kwh,
                f.load_forecast_kwh
            FROM slot_observations o
            JOIN slot_forecasts f
              ON o.slot_start = f.slot_start
            WHERE o.slot_start >= ? AND o.slot_start < ?
              AND f.forecast_version = ?
            """,
            (start_time.isoformat(), end_time.isoformat(), forecast_version),
        ).fetchall()

    if not rows:
        return None, None

    pv_errors: List[float] = []
    load_errors: List[float] = []

    for pv, load, pv_f, load_f in rows:
        if pv is not None and pv_f is not None:
            pv_errors.append(abs(float(pv) - float(pv_f)))
        if load is not None and load_f is not None:
            load_errors.append(abs(float(load) - float(load_f)))

    mae_pv = round(float(np.mean(pv_errors)), 4) if pv_errors else None
    mae_load = round(float(np.mean(load_errors)), 4) if load_errors else None
    return mae_pv, mae_load


def _print_segmented_mae(
    label: str,
    observations: pd.DataFrame,
    forecasts: List[Dict],
) -> None:
    """Print MAE segmented by simple context bands (weather/occupancy)."""
    if not forecasts or observations.empty:
        return

    obs = observations.copy()
    df_f = pd.DataFrame(forecasts)
    if df_f.empty:
        return

    df_f["slot_start"] = pd.to_datetime(
        df_f["slot_start"],
        format="ISO8601",
        utc=True,
        errors="coerce",
    )
    obs["slot_start"] = pd.to_datetime(
        obs["slot_start"],
        format="ISO8601",
        utc=True,
        errors="coerce",
    )
    merged = pd.merge(
        obs,
        df_f,
        on="slot_start",
        how="inner",
        suffixes=("_obs", "_pred"),
    )
    if merged.empty:
        return

    # Basic errors
    merged["pv_err"] = (merged["pv_kwh"] - merged["pv_forecast_kwh"]).abs()
    merged["load_err"] = (merged["load_kwh"] - merged["load_forecast_kwh"]).abs()

    # Weather bands: cold vs mild using s_index temp_baseline_c if available
    temp_baseline = (
        merged.get("temp_baseline_c")
        if "temp_baseline_c" in merged
        else None
    )
    if temp_baseline is None:
        temp_baseline = (
            merged["temp_c"].median()
            if "temp_c" in merged.columns and merged["temp_c"].notna().any()
            else None
        )

    print(f"--- Segmented MAE ({label}) ---")

    if temp_baseline is not None and "temp_c" in merged.columns:
        cold = merged[merged["temp_c"] <= temp_baseline]
        mild = merged[merged["temp_c"] > temp_baseline]
        if not cold.empty:
            print(
                f"  Cold (temp_c <= {temp_baseline:.1f}): "
                f"pv_mae={cold['pv_err'].mean():.4f}, "
                f"load_mae={cold['load_err'].mean():.4f}",
            )
        if not mild.empty:
            print(
                f"  Mild (temp_c > {temp_baseline:.1f}): "
                f"pv_mae={mild['pv_err'].mean():.4f}, "
                f"load_mae={mild['load_err'].mean():.4f}",
            )

    # Occupancy bands: vacation vs normal
    if "vacation_mode_flag" in merged.columns:
        vac = merged[merged["vacation_mode_flag"] >= 0.5]
        normal = merged[merged["vacation_mode_flag"] < 0.5]
        if not vac.empty:
            print(
                f"  Vacation ON: pv_mae={vac['pv_err'].mean():.4f}, "
                f"load_mae={vac['load_err'].mean():.4f}",
            )
        if not normal.empty:
            print(
                f"  Vacation OFF: pv_mae={normal['pv_err'].mean():.4f}, "
                f"load_mae={normal['load_err'].mean():.4f}",
            )

    # Security bands: alarm armed vs disarmed
    if "alarm_armed_flag" in merged.columns:
        armed = merged[merged["alarm_armed_flag"] >= 0.5]
        disarmed = merged[merged["alarm_armed_flag"] < 0.5]
        if not armed.empty:
            print(
                f"  Alarm ARMED: pv_mae={armed['pv_err'].mean():.4f}, "
                f"load_mae={armed['load_err'].mean():.4f}",
            )
        if not disarmed.empty:
            print(
                f"  Alarm DISARMED: pv_mae={disarmed['pv_err'].mean():.4f}, "
                f"load_mae={disarmed['load_err'].mean():.4f}",
            )


def main() -> None:
    args = _parse_args()
    cfg = EvaluationConfig(
        days_back=args.days_back,
        aurora_version=args.aurora_version,
        baseline_version=args.baseline_version,
    )

    print("--- Starting AURORA Evaluation (Rev 5) ---")

    try:
        engine = get_learning_engine()
        assert isinstance(engine, LearningEngine)
        print(f"Loaded LearningEngine with DB at: {engine.db_path}")
    except Exception as exc:  # pragma: no cover
        print(f"Error: Could not initialize LearningEngine. {exc}")
        return

    now = datetime.now(engine.timezone)
    start_time = now - timedelta(days=max(cfg.days_back, 1))
    print(
        "Evaluation window: "
        f"{start_time.isoformat()} to {now.isoformat()} "
        f"({cfg.days_back} days back).",
    )

    observations = _load_slot_observations(engine, start_time, now)
    if observations.empty:
        print("Error: No slot_observations found for evaluation window.")
        return

    # Enrich with hourly weather where available (temp, cloud, radiation)
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

    for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
        if col in observations.columns:
            observations[col] = pd.to_numeric(observations[col], errors="coerce")

    # Enrich with vacation_mode flag where available
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

    # Enrich with alarm_armed_flag where available
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

    # Build features consistent with training
    features = _build_time_features(observations)

    # Load trained models (as boosters)
    load_model_path = cfg.models_dir / cfg.load_model_name
    pv_model_path = cfg.models_dir / cfg.pv_model_name
    boosters: Dict[str, lgb.Booster | None] = {
        "load": _load_model(load_model_path),
        "pv": _load_model(pv_model_path),
    }

    # Generate and store baseline forecasts (simple 7-day average)
    baseline_forecasts = _generate_baseline_forecasts(observations, engine)
    if baseline_forecasts:
        engine.store_forecasts(baseline_forecasts, cfg.baseline_version)
        print(
            f"Stored {len(baseline_forecasts)} baseline forecasts "
            f"as version '{cfg.baseline_version}'.",
        )
    else:
        print("Warning: No baseline forecasts generated.")

    # Generate and store AURORA forecasts
    aurora_forecasts = _predict_with_boosters(
        {k: v for k, v in boosters.items() if v is not None},
        features,
        observations,
        engine,
        cfg.aurora_version,
    )
    if aurora_forecasts:
        engine.store_forecasts(aurora_forecasts, cfg.aurora_version)
        print(
            f"Stored {len(aurora_forecasts)} AURORA forecasts "
            f"as version '{cfg.aurora_version}'.",
        )
    else:
        print("Warning: No AURORA forecasts generated.")

    # Calculate MAE for both versions
    mae_pv_baseline, mae_load_baseline = _calculate_mae(
        engine,
        start_time,
        now,
        cfg.baseline_version,
    )
    mae_pv_aurora, mae_load_aurora = _calculate_mae(
        engine,
        start_time,
        now,
        cfg.aurora_version,
    )

    print("--- Evaluation Summary ---")
    print(f"Window: {start_time.date()} to {now.date()}")
    print(f"Baseline version: {cfg.baseline_version}")
    print(f"AURORA version:   {cfg.aurora_version}")
    print(f"Baseline MAE PV:   {mae_pv_baseline}")
    print(f"Baseline MAE load: {mae_load_baseline}")
    print(f"AURORA MAE PV:     {mae_pv_aurora}")
    print(f"AURORA MAE load:   {mae_load_aurora}")
    _print_segmented_mae("Baseline", observations, baseline_forecasts)
    _print_segmented_mae("AURORA", observations, aurora_forecasts)
    print("--- AURORA Evaluation finished ---")


if __name__ == "__main__":
    main()
