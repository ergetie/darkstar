from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from learning import get_learning_engine

from ml.forward import _load_models
from ml.train import _build_time_features, _load_slot_observations
from ml.weather import get_weather_series


def diagnose_pv():
    print("--- ☀️ AURORA PV DIAGNOSTICS ---")
    engine = get_learning_engine()
    now = datetime.now(engine.timezone)

    # 1. CHECK DATA
    print("\n1. TRAINING DATA CHECK")
    # Load all data (relaxed filter to see what it learned)
    df = _load_slot_observations(engine, now - timedelta(days=90), now)
    if not df.empty:
        max_pv = df["pv_kwh"].max()
        print(f"   Max PV in training data: {max_pv:.4f} kWh")
        if max_pv > 10:
            print(f"   🚨 CRITICAL: Found massive PV spike ({max_pv} kWh). This breaks the model.")
    else:
        print("   ❌ No training data.")

    # 2. DISSECT 16:00 PREDICTION
    # Target: Today at 16:00 (4 PM)
    target_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if target_time < now - timedelta(hours=24):
        target_time += timedelta(days=1)  # Look forward if passed long ago

    print(f"\n2. PREDICTION FOR: {target_time}")

    obs = pd.DataFrame({"slot_start": [target_time]})

    # Enrich
    weather_df = get_weather_series(
        target_time, target_time + timedelta(minutes=15), config=engine.config
    )
    if not weather_df.empty:
        obs = obs.merge(weather_df, left_on="slot_start", right_index=True, how="left")
        print(
            f"   Weather Forecast: Rad={obs['shortwave_radiation_w_m2'].iloc[0]} W/m2, Cloud={obs['cloud_cover_pct'].iloc[0]}%"
        )
    else:
        print("   ⚠️ No weather data found for this slot.")
        obs["temp_c"] = 0.0
        obs["cloud_cover_pct"] = 0.0
        obs["shortwave_radiation_w_m2"] = 0.0

    # Context (Defaults)
    obs["vacation_mode_flag"] = 0.0
    obs["alarm_armed_flag"] = 0.0

    obs = _build_time_features(obs)

    models = _load_models()
    if "pv" not in models:
        print("❌ PV model not found.")
        return

    trained_features = models["pv"].feature_name()
    for feat in trained_features:
        if feat not in obs.columns:
            obs[feat] = 0.0

    # Predict
    X_input = obs[trained_features]
    final_pred = models["pv"].predict(X_input)[0]
    print(f"   🔮 Raw PV Prediction: {final_pred:.4f} kWh")

    # Attribution
    try:
        pred_contrib = models["pv"].predict(X_input, pred_contrib=True)
        contributions = pred_contrib[0][:-1]
        impacts = sorted(
            zip(trained_features, contributions, strict=False), key=lambda x: abs(x[1]), reverse=True
        )

        print("\n   🏆 Top Drivers:")
        for feat, impact in impacts[:5]:
            print(f"      {feat:<25} {impact:+.4f}")
    except:
        pass


if __name__ == "__main__":
    diagnose_pv()
