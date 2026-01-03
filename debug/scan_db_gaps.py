import sqlite3
from datetime import timedelta

import pandas as pd
import pytz

DB_PATH = "data/planner_learning.db"
TZ = pytz.timezone("Europe/Stockholm")


def scan_gaps():
    print(f"Scanning {DB_PATH} for load gaps...")

    with sqlite3.connect(DB_PATH) as conn:
        # Get all slots sorted by time
        query = "SELECT slot_start, load_kwh FROM slot_observations ORDER BY slot_start"
        df = pd.read_sql_query(query, conn)

    if df.empty:
        print("Database is empty!")
        return

    # Convert to datetime
    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True).dt.tz_convert(TZ)

    # Find slots with zero/null/low load
    # We focus on load for now as that's critical
    missing = df[(df["load_kwh"] < 0.01) | (df["load_kwh"].isnull())]

    print(f"\nTotal Slots: {len(df)}")
    print(f"Zero/Null/Low Load Slots: {len(missing)} ({len(missing) / len(df) * 100:.2f}%)")

    if not missing.empty:
        print("\nTop Zero/Low-Load Periods:")
        # Group consecutive zero slots
        missing["group"] = (missing["slot_start"].diff() > timedelta(minutes=15)).cumsum()
        for _, group in missing.groupby("group"):
            start = group["slot_start"].iloc[0]
            end = group["slot_start"].iloc[-1]
            count = len(group)
            if count > 4:  # Only show gaps > 1 hour
                print(f"  {start} - {end} ({count} slots / {count * 15 / 60:.1f} hours)")

    # Check for Time Gaps (Missing Rows)
    df["delta"] = df["slot_start"].diff()
    gaps = df[df["delta"] > timedelta(minutes=15)]

    print(f"\nTime Gaps (Missing Rows): {len(gaps)}")
    if not gaps.empty:
        print("\nTop Time Gaps:")
        for _, row in gaps.head(20).iterrows():
            gap_start = row["slot_start"] - row["delta"]
            gap_end = row["slot_start"]
            duration = row["delta"]
            print(f"  {gap_start} -> {gap_end} (Missing {duration})")


if __name__ == "__main__":
    scan_gaps()
