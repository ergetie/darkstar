from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import lightgbm as lgb
import pandas as pd

from backend.learning import LearningEngine, get_learning_engine
from ml.context_features import get_alarm_armed_series, get_vacation_mode_series
from ml.train import _build_time_features
from ml.weather import get_weather_series


def _load_models(models_dir: str = "ml/models") -> dict[str, lgb.Booster]:
    """Load trained LightGBM models for AURORA forward inference (Probabilistic)."""
    models: dict[str, lgb.Booster] = {}

    # Quantiles to load
    quantiles = ["p10", "p50", "p90"]

    # Load Load Models
    for q in quantiles:
        # Try specific quantile file first
        path = f"{models_dir}/load_model_{q}.lgb"
        try:
            models[f"load_{q}"] = lgb.Booster(model_file=path)
        except Exception:
            # Fallback for p50: try legacy name
            if q == "p50":
                try:
                    models[f"load_{q}"] = lgb.Booster(model_file=f"{models_dir}/load_model.lgb")
                except Exception as exc:
                    print(f"Info: Could not load load_model ({q}): {exc}")
            else:
                print(f"Info: Could not load load_model_{q}.lgb")

    # Load PV Models
    for q in quantiles:
        path = f"{models_dir}/pv_model_{q}.lgb"
        try:
            models[f"pv_{q}"] = lgb.Booster(model_file=path)
        except Exception:
            if q == "p50":
                try:
                    models[f"pv_{q}"] = lgb.Booster(model_file=f"{models_dir}/pv_model.lgb")
                except Exception as exc:
                    print(f"Info: Could not load pv_model ({q}): {exc}")
            else:
                print(f"Info: Could not load pv_model_{q}.lgb")

    return models


def generate_forward_slots(
    horizon_hours: int = 168,
    forecast_version: str = "aurora",
) -> None:
    """
    Generate forward AURORA forecasts for the next horizon_hours.
    Includes probabilistic bands (p10, p50, p90).
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

    # Ensure ALL weather columns exist (even if empty) to match trained model feature count
    for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
        if col not in df.columns:
            df[col] = float("nan")
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

    # All 11 features required by trained models - we ensure all columns exist above
    feature_cols = [
        "hour",
        "day_of_week",
        "month",
        "is_weekend",
        "hour_sin",
        "hour_cos",
        "temp_c",
        "cloud_cover_pct",
        "shortwave_radiation_w_m2",
        "vacation_mode_flag",
        "alarm_armed_flag",
    ]

    print("   Running LightGBM inference (Probabilistic)...")
    X = df[feature_cols]
    models = _load_models()

    quantiles = ["p10", "p50", "p90"]
    predictions = {}

    # Initialize prediction series map
    for q in quantiles:
        predictions[f"load_{q}"] = pd.Series(0.0, index=df.index)
        predictions[f"pv_{q}"] = pd.Series(0.0, index=df.index)

    # --- LOAD INFERENCE ---
    for q in quantiles:
        model_key = f"load_{q}"
        if model_key in models:
            raw_pred = models[model_key].predict(X)
            # Apply guardrails (same for all bands)
            # Floor at 0.01, Ceiling at 16kW
            cleaned = [max(0.01, min(float(x), 16.0)) for x in raw_pred]
            predictions[model_key] = pd.Series(cleaned, index=df.index)

    # --- PV INFERENCE ---
    # Setup Astro Clamping
    sun_calc = None
    try:
        from backend.astro import SunCalculator

        lat = engine.config.get("system", {}).get("location", {}).get("latitude", 59.3293)
        lon = engine.config.get("system", {}).get("location", {}).get("longitude", 18.0686)
        sun_calc = SunCalculator(latitude=lat, longitude=lon, timezone=str(tz))
    except Exception as e:
        print(f"⚠️ Astro init failed: {e}")

    for q in quantiles:
        model_key = f"pv_{q}"
        if model_key in models:
            raw_pred = models[model_key].predict(X)

            series = pd.Series(0.0, index=df.index)
            for idx, row in df.iterrows():
                val = float(max(raw_pred[idx], 0.0))
                slot_ts = row["slot_start"]

                # 1. Astro Clamp
                is_sun_up = False
                if sun_calc:
                    is_sun_up = sun_calc.is_sun_up(slot_ts, buffer_minutes=30)
                else:
                    # Fallback
                    h = slot_ts.hour
                    is_sun_up = 5 <= h < 22

                if not is_sun_up:
                    val = 0.0

                # 2. Radiation Clamp
                rad = row.get("shortwave_radiation_w_m2")
                if rad is not None and rad < 1.0:
                    val = 0.0

                series[idx] = val

            # 3. Smoothing (Rolling Average)
            # Apply to all bands to prevent sawtooth
            predictions[model_key] = (
                series.rolling(window=3, center=True, min_periods=1).mean().fillna(0.0)
            )

    # --- STORE RESULTS ---
    forecasts: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        item = {
            "slot_start": row["slot_start"].isoformat(),
            "temp_c": row.get("temp_c"),
            # Primary (Legacy/p50)
            "pv_forecast_kwh": float(predictions["pv_p50"][idx]),
            "load_forecast_kwh": float(predictions["load_p50"][idx]),
            # Probabilistic Bands
            "pv_p10": float(predictions["pv_p10"][idx]),
            "pv_p90": float(predictions["pv_p90"][idx]),
            "load_p10": float(predictions["load_p10"][idx]),
            "load_p90": float(predictions["load_p90"][idx]),
        }
        forecasts.append(item)

    if forecasts:
        engine.store_forecasts(forecasts, forecast_version=forecast_version)
        print(f"✅ Stored {len(forecasts)} forward AURORA forecasts ({forecast_version}).")


if __name__ == "__main__":
    generate_forward_slots()
