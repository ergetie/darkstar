import sqlite3
from datetime import datetime

import pandas as pd
from learning import get_learning_engine

engine = get_learning_engine()
tz = engine.timezone
now = datetime.now(tz)

print("\n--- VERIFYING CORRECTIONS ---")
print(f"Current Time: {now}")

with sqlite3.connect(engine.db_path) as conn:
    # Fetch all aurora forecasts
    df = pd.read_sql("SELECT * FROM slot_forecasts WHERE forecast_version='aurora'", conn)

if df.empty:
    print("❌ No 'aurora' rows found in DB.")
else:
    # Robust date parsing (handles mixed formats automatically)
    df["slot_start"] = pd.to_datetime(df["slot_start"], format="mixed", utc=True).dt.tz_convert(tz)

    # Filter for FUTURE slots only
    future_df = df[df["slot_start"] > now].sort_values("slot_start").head(10)

    if future_df.empty:
        print("❌ No future rows found (Check if 'run_planner.py' actually ran).")
    else:
        print(
            future_df[
                [
                    "slot_start",
                    "pv_forecast_kwh",
                    "pv_correction_kwh",
                    "load_correction_kwh",
                    "correction_source",
                ]
            ].to_string(index=False)
        )
