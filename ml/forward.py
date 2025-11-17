from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import lightgbm as lgb
import pandas as pd
import pytz

from learning import LearningEngine, get_learning_engine
from ml.train import _build_time_features
from ml.weather import get_weather_series
from ml.context_features import get_vacation_mode_series, get_alarm_armed_series


def _load_models(models_dir: str = "ml/models") -> Dict[str, lgb.Booster]:
    """Load trained LightGBM models for AURORA forward inference."""
    load_path = f"{models_dir}/load_model.lgb"
    pv_path = f"{models_dir}/pv_model.lgb"
    models: Dict[str, lgb.Booster] = {}
    try:
        models["load"] = lgb.Booster(model_file=load_path)
    except Exception as exc:  # pragma: no cover
        print(f"Warning: Could not load load_model.lgb: {exc}")
    try:
        models["pv"] = lgb.Booster(model_file=pv_path)
    except Exception as exc:  # pragma: no cover
        print(f"Warning: Could not load pv_model.lgb: {exc}")
    return models


def generate_forward_slots(
    horizon_hours: int = 48,
    forecast_version: str = "aurora",
) -> None:
    """
    Generate forward AURORA forecasts for the next horizon_hours and
    store them into slot_forecasts.

    This does not change planner behaviour; it only populates the DB.
    """
    engine = get_learning_engine()
    assert isinstance(engine, LearningEngine)

    tz = engine.timezone
    now = datetime.now(tz)

    # Align to next slot boundary (assume 15-minute slots)
    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)

    horizon_end = slot_start + timedelta(hours=horizon_hours)

    slots = pd.date_range(
        start=slot_start,
        end=horizon_end,
        freq="15min",
        tz=tz,
        inclusive="left",
    )
    if len(slots) == 0:
        print("No future slots to forecast.")
        return

    df = pd.DataFrame({"slot_start": slots})

    # Enrich with forecast weather where available (temp, cloud cover, radiation)
    weather_df = get_weather_series(slot_start, horizon_end, config=engine.config)
    if not weather_df.empty:
        df = df.merge(weather_df, left_on="slot_start", right_index=True, how="left")
    else:
        df["temp_c"] = None
    # Ensure numeric dtypes even when values are missing/None
    if "temp_c" in df.columns:
        df["temp_c"] = df["temp_c"].astype("float64")
    if "cloud_cover_pct" in df.columns:
        df["cloud_cover_pct"] = df["cloud_cover_pct"].astype("float64")
    if "shortwave_radiation_w_m2" in df.columns:
        df["shortwave_radiation_w_m2"] = df["shortwave_radiation_w_m2"].astype("float64")

    # Enrich with context flags based on recent HA history (best effort)
    vac_series = get_vacation_mode_series(slot_start - timedelta(days=7), horizon_end, config=engine.config)
    if not vac_series.empty:
        df = df.merge(
            vac_series.to_frame(name="vacation_mode_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        df["vacation_mode_flag"] = 0.0

    alarm_series = get_alarm_armed_series(slot_start - timedelta(days=7), horizon_end, config=engine.config)
    if not alarm_series.empty:
        df = df.merge(
            alarm_series.to_frame(name="alarm_armed_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        df["alarm_armed_flag"] = 0.0

    df = _build_time_features(df)

    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    if "temp_c" in df.columns:
        feature_cols.append("temp_c")
    if "cloud_cover_pct" in df.columns:
        feature_cols.append("cloud_cover_pct")
    if "shortwave_radiation_w_m2" in df.columns:
        feature_cols.append("shortwave_radiation_w_m2")
    if "vacation_mode_flag" in df.columns:
        feature_cols.append("vacation_mode_flag")
    if "alarm_armed_flag" in df.columns:
        feature_cols.append("alarm_armed_flag")

    X = df[feature_cols]

    models = _load_models()
    if not models:
        print("No AURORA models loaded; aborting forward inference.")
        return

    load_pred = models["load"].predict(X) if "load" in models else None
    pv_pred = models["pv"].predict(X) if "pv" in models else None

    forecasts: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        slot_start_ts = row["slot_start"]
        record: Dict[str, Any] = {
            "slot_start": slot_start_ts.isoformat(),
            "pv_forecast_kwh": 0.0,
            "load_forecast_kwh": 0.0,
            "temp_c": row.get("temp_c"),
        }
        if load_pred is not None:
            record["load_forecast_kwh"] = float(max(load_pred[idx], 0.0))
        if pv_pred is not None:
            record["pv_forecast_kwh"] = float(max(pv_pred[idx], 0.0))
        forecasts.append(record)

    if not forecasts:
        print("No forecasts generated for forward horizon.")
        return

    engine.store_forecasts(forecasts, forecast_version=forecast_version)
    print(
        f"Stored {len(forecasts)} forward AURORA forecasts "
        f"({forecast_version}) from {slot_start} to {horizon_end}."
    )


if __name__ == "__main__":
    generate_forward_slots()
