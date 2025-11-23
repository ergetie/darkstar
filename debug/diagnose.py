from __future__ import annotations

import sqlite3
import pandas as pd
import lightgbm as lgb
import numpy as np
import pytz
from datetime import datetime, timedelta
from pathlib import Path

from learning import get_learning_engine
from ml.train import _build_time_features, _load_slot_observations
from ml.forward import _load_models
from ml.weather import get_weather_series
from ml.context_features import get_vacation_mode_series, get_alarm_armed_series


def diagnose():
    print("--- 🏥 AURORA DIAGNOSTICS TOOL (Fixed) ---")
    engine = get_learning_engine()

    # 1. INSPECT TRAINING DATA DISTRIBUTION
    print("\n1. INSPECTING TRAINING DATA")
    now = datetime.now(engine.timezone)
    start_time = now - timedelta(days=90)

    df = _load_slot_observations(engine, start_time, now)

    if df.empty:
        print("❌ No training data found.")
        return

    df = _build_time_features(df)

    hourly_counts = df.groupby("hour").size()
    missing_hours = [h for h in range(24) if h not in hourly_counts.index]

    if missing_hours:
        print(f"   ⚠️ CRITICAL: Model has NO DATA for hours: {missing_hours}")
        print("      Predictions for these times are pure guesses (hallucinations).")
    else:
        print("   ✅ Training data covers all 24 hours.")

    # 2. DISSECT THE PREDICTION
    target_time = now.replace(hour=4, minute=15, second=0, microsecond=0)
    if target_time < now:
        target_time += timedelta(days=1)

    print(f"\n2. DISSECTING PREDICTION FOR: {target_time}")

    obs = pd.DataFrame({"slot_start": [target_time]})

    # Enrich (Robustly)
    weather_df = get_weather_series(
        target_time, target_time + timedelta(minutes=15), config=engine.config
    )
    if not weather_df.empty:
        obs = obs.merge(weather_df, left_on="slot_start", right_index=True, how="left")
    else:
        obs["temp_c"] = None

    # Ensure ALL potential features exist (Fixing the crash)
    for col in ["temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"]:
        if col not in obs.columns:
            obs[col] = 0.0  # Default to 0/None if missing
        obs[col] = obs[col].astype("float64")

    vac_series = get_vacation_mode_series(
        target_time - timedelta(days=1), target_time + timedelta(days=1), config=engine.config
    )
    if not vac_series.empty:
        obs = obs.merge(
            vac_series.to_frame(name="vacation_mode_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        obs["vacation_mode_flag"] = 0.0

    alarm_series = get_alarm_armed_series(
        target_time - timedelta(days=1), target_time + timedelta(days=1), config=engine.config
    )
    if not alarm_series.empty:
        obs = obs.merge(
            alarm_series.to_frame(name="alarm_armed_flag"),
            left_on="slot_start",
            right_index=True,
            how="left",
        )
    else:
        obs["alarm_armed_flag"] = 0.0

    obs = _build_time_features(obs)

    # Define features exactly as train.py does
    # We must manually ensure the list matches the training set order/count
    # Standard features:
    feature_cols = ["hour", "day_of_week", "month", "is_weekend", "hour_sin", "hour_cos"]
    # Optional features (Must match what was available during training)
    # Note: If training had them and we don't, we pad. If we have them but training didn't, we ignore.
    # Ideally we load the model and check model.feature_name() but that requires loading first.

    models = _load_models()
    if "load" not in models:
        print("❌ Load model not found.")
        return

    trained_features = models["load"].feature_name()
    print(f"   Model expects features: {trained_features}")

    # Ensure our input dataframe has all columns the model wants
    for feat in trained_features:
        if feat not in obs.columns:
            obs[feat] = 0.0

    # Use exactly the features the model was trained on
    X_input = obs[trained_features]

    # Predict
    final_pred = models["load"].predict(X_input)[0]
    print(f"   🔮 Raw Model Prediction: {final_pred:.4f} kWh")

    if final_pred > 2.0:
        print("   🚨 HIGH VALUE DETECTED.")

    # Feature Contribution (SHAP-like)
    try:
        pred_contrib = models["load"].predict(X_input, pred_contrib=True)
        contributions = pred_contrib[0][:-1]
        impacts = list(zip(trained_features, contributions))
        impacts.sort(key=lambda x: abs(x[1]), reverse=True)

        print("\n   🏆 Top Drivers (What pushed the value up?):")
        for feat, impact in impacts:
            sign = "+" if impact > 0 else ""
            print(f"      {feat:<25} {sign}{impact:.4f}")
    except Exception as e:
        print(f"   (Could not calculate detailed attribution: {e})")


if __name__ == "__main__":
    diagnose()
