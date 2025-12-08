from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import lightgbm as lgb
import pandas as pd
import pytz

from backend.learning import LearningEngine, get_learning_engine
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
    except Exception as exc:
        print(f"Info: Could not load load_model.lgb ({exc})")
    try:
        models["pv"] = lgb.Booster(model_file=pv_path)
    except Exception as exc:
        print(f"Info: Could not load pv_model.lgb ({exc})")
    return models


def generate_forward_slots(
    horizon_hours: int = 168,  # Changed from 48 to 168 (7 days) for S-index support
    forecast_version: str = "aurora",
) -> None:
    """
    Generate forward AURORA forecasts for the next horizon_hours.
    Includes strict guardrails and smoothing for PV.
    """
    engine = get_learning_engine()
    assert isinstance(engine, LearningEngine)

    tz = engine.timezone
    now = datetime.now(tz)

    # Align to next slot
    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)

    horizon_end = slot_start + timedelta(hours=horizon_hours)

    print(f"🔮 Generating AURORA Forecast: {slot_start} -> {horizon_end} ({horizon_hours}h)")

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

    # Enrich with forecast weather
    print("   Fetching weather data...")
    weather_df = get_weather_series(slot_start, horizon_end, config=engine.config)
    if not weather_df.empty:
        df = df.merge(weather_df, left_on="slot_start", right_index=True, how="left")
    else:
        df["temp_c"] = None

    # Ensure numeric dtypes
    for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
        if col in df.columns:
            df[col] = df[col].astype("float64")

    # Context flags
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

    alarm_series = get_alarm_armed_series(
        slot_start - timedelta(days=7), horizon_end, config=engine.config
    )
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

    feature_cols = ["hour", "day_of_week", "month", "is_weekend", "hour_sin", "hour_cos"]
    for feat in [
        "temp_c",
        "cloud_cover_pct",
        "shortwave_radiation_w_m2",
        "vacation_mode_flag",
        "alarm_armed_flag",
    ]:
        if feat in df.columns:
            feature_cols.append(feat)

    print("   Running LightGBM inference...")
    X = df[feature_cols]
    models = _load_models()

    load_pred = models["load"].predict(X) if "load" in models else None
    pv_pred = models["pv"].predict(X) if "pv" in models else None

    # Create temporary Series for smoothing
    pv_series = pd.Series(0.0, index=df.index)
    load_series = pd.Series(0.0, index=df.index)

    for idx, row in df.iterrows():
        slot_start_ts = row["slot_start"]

        if load_pred is not None:
            raw_val = float(load_pred[idx])
            # Guardrail: Floor at 0.01, Ceiling at 4.0 (16kW)
            load_series[idx] = max(0.01, min(raw_val, 4.0))

        if pv_pred is not None:
            pv_val = float(max(pv_pred[idx], 0.0))

            # Guardrail: Astro-Aware PV Clamp
            # Use SunCalculator to check if sun is up (with 30min buffer)
            # This handles seasonal variations (winter darkness vs summer light)
            try:
                from backend.astro import SunCalculator
                
                # Get location from config or defaults
                lat = engine.config.get("system", {}).get("location", {}).get("latitude", 59.3293)
                lon = engine.config.get("system", {}).get("location", {}).get("longitude", 18.0686)
                
                sun_calc = SunCalculator(latitude=lat, longitude=lon, timezone=str(tz))
                
                if not sun_calc.is_sun_up(slot_start_ts, buffer_minutes=30):
                    pv_val = 0.0
            except Exception as e:
                print(f"⚠️ Astro calculation failed: {e}. Fallback to hour check.")
                # Fallback to simple hour check if astral fails
                hour = slot_start_ts.hour
                if hour < 5 or hour >= 22: # Generous fallback
                    pv_val = 0.0

            # Guardrail: Radiation check
            rad = row.get("shortwave_radiation_w_m2")
            if rad is not None and rad < 1.0:
                pv_val = 0.0

            pv_series[idx] = pv_val

    # SMOOTHING: Apply a rolling average to PV to fix "Sawtooth"
    pv_series = pv_series.rolling(window=3, center=True, min_periods=1).mean().fillna(0.0)

    forecasts: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        forecasts.append(
            {
                "slot_start": row["slot_start"].isoformat(),
                "pv_forecast_kwh": float(pv_series[idx]),
                "load_forecast_kwh": float(load_series[idx]),
                "temp_c": row.get("temp_c"),
            }
        )

    if forecasts:
        engine.store_forecasts(forecasts, forecast_version=forecast_version)
        print(f"✅ Stored {len(forecasts)} forward AURORA forecasts ({forecast_version}).")


if __name__ == "__main__":
    generate_forward_slots()
