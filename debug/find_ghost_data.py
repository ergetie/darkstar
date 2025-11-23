import sqlite3
import pandas as pd
import os

DB_PATH = "data/planner_learning.db"


def inspect_ghosts():
    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    # Look for suspicious low load data between 14:00 and 20:00 (where your adjustments are negative)
    print("🔍 Searching for invalid zero-load readings in history...")

    query = """
    SELECT slot_start, load_kwh, pv_kwh 
    FROM slot_observations 
    WHERE cast(strftime('%H', slot_start) as int) BETWEEN 14 AND 20
      AND load_kwh < 0.05
    ORDER BY slot_start DESC
    LIMIT 100
    """

    try:
        df = pd.read_sql_query(query, conn)
        if not df.empty:
            print(f"⚠️ FOUND {len(df)} SUSPICIOUS RECORDS (Showing max 100):")
            print(df.to_string(index=False))
            print(
                "\nAnalysis: These 'near zero' values are dragging your forecast down into the negatives."
            )
        else:
            print(
                "✅ No obvious zero-load records found. The bias might be from general low usage vs high forecast."
            )

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    inspect_ghosts()
