import sys
import os
import sqlite3
import pandas as pd

sys.path.append(os.getcwd())
from backend.learning.store import LearningStore
import pytz
from datetime import datetime

DB_PATH = "data/planner_learning.db"


def check_prod_data():
    store = LearningStore(DB_PATH, pytz.UTC)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check Max Timestamps
    cursor.execute("SELECT MAX(slot_start) FROM slot_observations")
    last_obs = cursor.fetchone()[0]

    cursor.execute("SELECT MAX(slot_start) FROM slot_forecasts")
    last_fc = cursor.fetchone()[0]

    print(f"Last Observation: {last_obs}")
    print(f"Last Forecast:    {last_fc}")

    now = datetime.now(pytz.UTC)
    print(f"Current Time:     {now}")

    # Try the join call
    print("\nAttempting get_forecast_vs_actual(days_back=7)...")
    df = store.get_forecast_vs_actual(days_back=7, target="pv")
    print(f"Rows returned: {len(df)}")

    if len(df) > 0:
        print("Latest Data:")
        print(df[["slot_start", "actual", "p10", "p90"]].tail(3))

        # Check P-values specifically for NULLs
        null_p = df[df["p10"].isnull()]
        print(f"\nRows with NULL p10: {len(null_p)}")
        if len(null_p) < len(df):
            print("Some rows have P-values!")
    else:
        print("Join returned 0 rows even for 7 days back.")

    conn.close()


if __name__ == "__main__":
    check_prod_data()
