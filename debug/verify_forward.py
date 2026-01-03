import os
import sqlite3
from datetime import datetime

import pandas as pd
import pytz

DB_PATH = "data/planner_learning.db"


def verify():
    print(f"🔍 Verifying Forward Forecasts in {DB_PATH}...")

    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    # Get 'aurora' version forecasts
    query = """
    SELECT slot_start, load_forecast_kwh, pv_forecast_kwh
    FROM slot_forecasts
    WHERE forecast_version='aurora'
    ORDER BY slot_start ASC
    """

    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"❌ Error reading DB: {e}")
        return
    finally:
        conn.close()

    if df.empty:
        print("❌ No 'aurora' forecasts found.")
        return

    # Fix timestamps and handle timezone
    try:
        df["dt"] = pd.to_datetime(df["slot_start"], format="mixed", utc=True).dt.tz_convert(
            "Europe/Stockholm"
        )
    except:
        df["dt"] = pd.to_datetime(df["slot_start"], utc=True).dt.tz_convert("Europe/Stockholm")

    # CRITICAL FIX: Only verify FUTURE slots (The Forward Forecasts)
    # The DB also contains PAST slots from the evaluation run (Backtest),
    # which intentionally lack guardrails to test raw model performance.
    now = datetime.now(pytz.timezone("Europe/Stockholm"))
    future_df = df[df["dt"] >= now].copy()

    print(f"✅ Found {len(df)} total rows (Backtest + Forward).")

    if future_df.empty:
        print("❌ No FUTURE forecasts found! Did ml/forward.py run?")
        return

    print(f"🔮 Verifying only the {len(future_df)} FUTURE slots...\n")

    # TEST 1: Load Guardrail
    min_load = future_df["load_forecast_kwh"].min()
    print(f"📉 Minimum Predicted Load: {min_load:.4f} kWh")
    if min_load >= 0.01:
        print("   ✅ PASS: Load Floor is working (>= 0.01)")
    else:
        print(f"   ❌ FAIL: Found load below 0.01! ({min_load})")

    # TEST 2: Night PV Guardrail (22:00 - 04:00)
    night_mask = (future_df["dt"].dt.hour >= 22) | (future_df["dt"].dt.hour < 4)
    night_df = future_df[night_mask]

    if not night_df.empty:
        max_night_pv = night_df["pv_forecast_kwh"].max()
        print(f"🌑 Max PV at Night (22:00-04:00): {max_night_pv:.4f} kWh")
        if max_night_pv == 0.0:
            print("   ✅ PASS: Night PV is hard-clamped to 0.")
        else:
            print("   ❌ FAIL: Solar production detected at night!")
    else:
        print("   ⚠️ Warning: No night slots found in future window.")

    print("\n📊 Sample Data (Next 5 slots):")
    print(
        future_df[["slot_start", "load_forecast_kwh", "pv_forecast_kwh"]]
        .head(5)
        .to_string(index=False)
    )


if __name__ == "__main__":
    verify()
