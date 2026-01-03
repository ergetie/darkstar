import sqlite3
from datetime import datetime, timedelta

import pandas as pd
from learning import get_learning_engine

engine = get_learning_engine()
tz = engine.timezone
now = datetime.now(tz)

# Target: Tomorrow Noon (+1 day, set to 12:00)
tomorrow_noon = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
window_start = tomorrow_noon - timedelta(hours=1)
window_end = tomorrow_noon + timedelta(hours=1)

print("\n--- VERIFYING PV CORRECTIONS (Midday) ---")
print(f"Target Window: {window_start.strftime('%Y-%m-%d %H:%M')} to {window_end.strftime('%H:%M')}")

with sqlite3.connect(engine.db_path) as conn:
    df = pd.read_sql("SELECT * FROM slot_forecasts WHERE forecast_version='aurora'", conn)

if df.empty:
    print("❌ No rows found.")
else:
    # Parse and Filter
    df["slot_start"] = pd.to_datetime(df["slot_start"], format="mixed", utc=True).dt.tz_convert(tz)

    day_df = df[(df["slot_start"] >= window_start) & (df["slot_start"] <= window_end)].sort_values(
        "slot_start"
    )

    if day_df.empty:
        print("❌ No forecasts found for tomorrow noon.")
    else:
        print(
            day_df[
                ["slot_start", "pv_forecast_kwh", "pv_correction_kwh", "correction_source"]
            ].to_string(index=False)
        )
