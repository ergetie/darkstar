import pandas as pd
import lightgbm as lgb
import joblib
from pathlib import Path
from ml.weather import get_weather_series
from ml.context_features import get_vacation_mode_series, get_alarm_armed_series
from datetime import datetime, timedelta
import pytz


def debug_forecast(target_time_str):
    """
    Deep dive into why the model predicts what it predicts for a specific time.
    """
    target_time = pd.to_datetime(target_time_str).tz_localize("Europe/Stockholm")
    print(f"\n--- Debugging Forecast for {target_time} ---")

    # 1. Load Models
    print("Loading models...")
    load_model = lgb.Booster(model_file="ml/models/load_model.lgb")
    pv_model = lgb.Booster(model_file="ml/models/pv_model.lgb")

    # 2. Reconstruct Features for the target slot
    print("Reconstructing features...")

    # Weather
    # We need a small window around the target to get the data
    start = target_time - timedelta(hours=1)
    end = target_time + timedelta(hours=1)

    weather_df = get_weather_series(start, end)
    # Find the row for our target time
    # Resample/reindex might be needed if exact match fails, but let's try exact first
    weather_row = weather_df.loc[weather_df.index == target_time]

    if weather_row.empty:
        print("ERROR: No weather data found for target time!")
        return

    # Context
    vacation = get_vacation_mode_series(start, end)
    alarm = get_alarm_armed_series(start, end)

    import numpy as np

    # Cyclical encodings for hour of day
    radians = 2 * np.pi * target_time.hour / 24.0

    # Build Feature Vector
    features = {
        "hour": target_time.hour,
        "day_of_week": target_time.dayofweek,
        "month": target_time.month,
        "is_weekend": 1 if target_time.dayofweek >= 5 else 0,
        "hour_sin": np.sin(radians),
        "hour_cos": np.cos(radians),
        "temp_c": weather_row["temp_c"].values[0],
        "cloud_cover_pct": (
            weather_row["cloud_cover_pct"].values[0] if "cloud_cover_pct" in weather_row else 0
        ),
        "shortwave_radiation_w_m2": (
            weather_row["shortwave_radiation_w_m2"].values[0]
            if "shortwave_radiation_w_m2" in weather_row
            else 0
        ),
        "vacation_mode_flag": 1 if vacation.get(target_time, 0) > 0 else 0,
        "alarm_armed_flag": 1 if alarm.get(target_time, 0) > 0 else 0,
    }

    feature_df = pd.DataFrame([features])

    print("\nInput Features:")
    print(feature_df.T)

    # 3. Predict and Explain
    print("\n--- Model Predictions ---")

    # Load
    load_pred = load_model.predict(feature_df)[0]
    print(f"Raw Load Prediction: {load_pred:.4f} kWh")

    # PV
    pv_pred = pv_model.predict(feature_df)[0]
    print(f"Raw PV Prediction:   {pv_pred:.4f} kWh")

    # 4. Feature Contribution (Shapley values would be best, but let's use simple split importance for now)
    # Actually, for a single prediction, we can't easily get contribution without shap.
    # Let's just print global importance to see what the model cares about.

    print("\n--- Global Feature Importance (Top 5) ---")
    print("Load Model:")
    # lgb.plot_importance(load_model, max_num_features=5, importance_type='split')
    # We can't plot in terminal, so let's print the arrays
    importance = pd.DataFrame(
        {"Feature": load_model.feature_name(), "Importance": load_model.feature_importance()}
    ).sort_values(by="Importance", ascending=False)
    print(importance.head(5))

    print("\nPV Model:")
    importance_pv = pd.DataFrame(
        {"Feature": pv_model.feature_name(), "Importance": pv_model.feature_importance()}
    ).sort_values(by="Importance", ascending=False)
    print(importance_pv.head(5))

    # 5. Safety Guardrails Check
    print("\n--- Safety Guardrails Check ---")

    # Load Floor
    final_load = max(load_pred, 0.01)
    print(f"Final Load (after 0.01 floor): {final_load:.4f}")

    # Night Clamp
    hour = target_time.hour
    final_pv = pv_pred
    if hour < 4 or hour >= 22:
        print(f"Night Clamp Active (22:00-04:00): Forcing PV to 0.0")
        final_pv = 0.0
    else:
        final_pv = max(pv_pred, 0.0)

    print(f"Final PV: {final_pv:.4f}")


if __name__ == "__main__":
    # Default to tonight at 23:00 if no arg provided
    # You can change this to test other slots
    target = "2025-11-20 23:00:00"
    debug_forecast(target)
