import json
import os
import sqlite3

import pandas as pd

DB_PATH = "data/planner_learning.db"


def check_learning():
    print(f"🔍 Inspecting {DB_PATH}...")

    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

        # Get the latest metrics
        query = """
        SELECT date, s_index_base_factor, load_adjustment_by_hour_kwh 
        FROM learning_daily_metrics 
        ORDER BY date DESC LIMIT 1
        """
        df = pd.read_sql_query(query, conn)

        if not df.empty:
            row = df.iloc[0]
            print(f"📅 Date: {row['date']}")

            # CHECK S-INDEX
            s_index = row.get("s_index_base_factor")
            print(f"\n🛡️  Stored S-Index Factor: {s_index}")
            if s_index is not None:
                print("   (⚠️  This value overrides your config.yaml!)")
            else:
                print("   (✅ None stored. Planner uses config.yaml)")

            # CHECK LOAD BIAS
            load_adj = (
                json.loads(row["load_adjustment_by_hour_kwh"])
                if row["load_adjustment_by_hour_kwh"]
                else []
            )
            print(f"\n📉 Load Adjustments (First 5 hours): {load_adj[:5]}")

        else:
            print("⚠️ No metrics found.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    check_learning()
