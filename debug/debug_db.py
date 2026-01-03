import os
import sqlite3

import pandas as pd

# This matches the path in your file list
DB_PATH = "data/planner_learning.db"


def check_db():
    print(f"🔍 inspecting {DB_PATH}...")

    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database file not found at {DB_PATH}")
        return

    try:
        # Connect in read-only mode just to be safe
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

        # specific columns we care about
        query = "SELECT slot_start, load_kwh, pv_kwh FROM slot_observations"
        try:
            df = pd.read_sql_query(query, conn)
        except pd.errors.DatabaseError as e:
            print(f"❌ Error: Could not read table. {e}")
            return

        if df.empty:
            print("⚠️ Table 'slot_observations' exists but is EMPTY.")
            return

        total_rows = len(df)

        # We define "Zero" as anything less than 0.001 kWh (1 Watt-hour)
        # A real house basically never uses 0.000 kWh in 15 minutes.
        zero_load = df[df["load_kwh"] <= 0.001]
        valid_load = df[df["load_kwh"] > 0.001]

        print("\n--- 🏠 LOAD (CONSUMPTION) DIAGNOSIS ---")
        print(f"Total Data Points:     {total_rows}")
        print(f"Valid Readings:        {len(valid_load)}")
        print(f" suspicious Zeros:     {len(zero_load)}  <-- THESE ARE THE GHOSTS")

        if len(zero_load) > 0:
            pct = (len(zero_load) / total_rows) * 100
            print(f"Data Corruption:       {pct:.1f}% of your data is zero.")

            avg_with_zeros = df["load_kwh"].mean()
            avg_without_zeros = valid_load["load_kwh"].mean()

            print("\n📉 IMPACT ON AI:")
            print(f"   Average WITH zeros:    {avg_with_zeros:.3f} kWh")
            print(f"   Average WITHOUT zeros: {avg_without_zeros:.3f} kWh")
            print(
                f"   >> The zeros are dragging predictions down by {avg_without_zeros - avg_with_zeros:.3f} kWh"
            )

            print("\n🕒 When are these zeros happening? (First 5 examples):")
            print(zero_load[["slot_start", "load_kwh"]].head(5).to_string(index=False))
        else:
            print("\n✅ No zero-load artifacts found! My hypothesis was wrong.")

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    check_db()
